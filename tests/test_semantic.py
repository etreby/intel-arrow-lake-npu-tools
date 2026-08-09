import errno
import shutil
import sqlite3
from pathlib import Path
from unittest import mock

import numpy as np
import pytest

from intel_npu_tools import semantic
from intel_npu_tools.semantic import SemanticIndex, chunk_text, iter_text_files


class FakePipeline:
    def _vector(self, text):
        lowered = text.lower()
        vector = np.array([
            lowered.count("apple"), lowered.count("engine"), lowered.count("network"), 1.0
        ], dtype=np.float32)
        return (vector / np.linalg.norm(vector)).tolist()

    def embed_documents(self, texts):
        return [self._vector(text) for text in texts]

    def embed_query(self, text):
        return self._vector(text)


def build_index(db_path: Path) -> SemanticIndex:
    return SemanticIndex(db_path, pipeline_factory=FakePipeline)


def test_chunk_text_tracks_lines():
    chunks = chunk_text("one\ntwo\nthree\nfour", target_chars=7, overlap_lines=1)
    assert chunks[0] == (1, 2, "one\ntwo")
    assert chunks[-1][1] == 4


def test_chunk_text_splits_a_single_overlong_line():
    """A minified line must not become one chunk whose tail the model truncates."""
    chunks = chunk_text("x" * 5000, max_chars=1500)
    assert len(chunks) == 4
    assert all(len(content) <= 1500 for _, _, content in chunks)
    assert "".join(content for _, _, content in chunks) == "x" * 5000


def test_hard_split_pieces_cite_only_the_lines_they_cover():
    """A split piece must not claim the whole surrounding range in search results."""
    long_line = "y" * 4000
    chunks = chunk_text(f"short\n{long_line}\ntail", target_chars=10, overlap_lines=0, max_chars=1500)

    assert chunks[0] == (1, 1, "short")
    assert chunks[-1] == (3, 3, "tail")
    from_long_line = [chunk for chunk in chunks if chunk[2].startswith("y")]
    assert all((start, end) == (2, 2) for start, end, _ in from_long_line)
    assert "".join(content for _, _, content in from_long_line) == long_line


def test_chunks_stay_within_the_model_character_budget():
    text = "\n".join(f"def function_{n}(): return {n}" for n in range(400))
    assert all(len(content) <= semantic.MAX_CHUNK_CHARS for _, _, content in chunk_text(text))


def test_index_and_semantic_search(tmp_path: Path):
    documents = tmp_path / "documents"
    documents.mkdir()
    (documents / "fruit.txt").write_text("Apples and pears are fruit.\n")
    (documents / "code.md").write_text("The rendering engine initializes the network.\n")
    index = build_index(tmp_path / "index.sqlite3")

    result = index.index(str(documents))
    assert result["files_updated"] == 2
    assert result["chunks_added"] == 2
    assert index.index(str(documents))["files_unchanged"] == 2

    hits = index.search("engine", limit=1)
    assert hits[0]["path"].endswith("code.md")
    assert hits[0]["start_line"] == 1
    assert index.status()["files"] == 2


def test_skip_dirs_ignore_directories_above_the_root(tmp_path: Path):
    """An ancestor named 'build' must not disqualify everything beneath it."""
    project = tmp_path / "build" / "project"
    project.mkdir(parents=True)
    (project / "main.py").write_text("value = 1\n")

    assert [path.name for path in iter_text_files(project)] == ["main.py"]


def test_source_directory_named_models_is_indexed(tmp_path: Path):
    project = tmp_path / "project"
    (project / "models").mkdir(parents=True)
    (project / "models" / "user.py").write_text("class User: pass\n")

    assert [path.name for path in iter_text_files(project)] == ["user.py"]


def test_directory_holding_model_weights_is_pruned_whole(tmp_path: Path):
    """Tokenizer and OpenVINO sidecars are .json/.txt/.xml, so only the weights beside them mark the directory."""
    project = tmp_path / "project"
    weights = project / "whisper-base-int8-ov"
    (weights / "extra").mkdir(parents=True)
    (weights / "openvino_model.bin").write_bytes(b"\x00\x01")
    (weights / "openvino_model.xml").write_text("<net><layer/></net>\n")
    (weights / "vocab.json").write_text('{"a": 1}\n')
    (weights / "merges.txt").write_text("a b\n")
    (weights / "extra" / "notes.md").write_text("# buried under the weights\n")
    (project / "app.py").write_text("print(1)\n")

    assert [path.name for path in iter_text_files(project)] == ["app.py"]


def test_cache_directories_are_skipped(tmp_path: Path):
    project = tmp_path / "project"
    (project / ".pytest_cache").mkdir(parents=True)
    (project / ".pytest_cache" / "README.md").write_text("# pytest cache\n")
    (project / "app.py").write_text("print(1)\n")

    assert [path.name for path in iter_text_files(project)] == ["app.py"]


def test_unreadable_files_are_not_pruned_from_the_index(tmp_path: Path):
    """A permission error or an unavailable mount must not erase rows for files that still exist."""
    notes = tmp_path / "notes.txt"
    notes.write_text("The engine runs.\n")
    index = build_index(tmp_path / "index.sqlite3")
    index.index(str(tmp_path))

    with sqlite3.connect(tmp_path / "index.sqlite3") as db:
        before = db.execute("SELECT count(*) FROM files").fetchone()[0]
    assert before == 1

    # An unreadable parent makes os.path.exists() answer False for a file that
    # is still on disk; only lstat's errno tells the two situations apart.
    with mock.patch.object(
        semantic.os, "lstat", side_effect=PermissionError(errno.EACCES, "denied")
    ), mock.patch.object(semantic.os.path, "exists", return_value=False):
        with semantic._connect(tmp_path / "index.sqlite3") as db:
            removed = index._prune_removed(db, tmp_path, set())

    assert removed == 0
    with sqlite3.connect(tmp_path / "index.sqlite3") as db:
        assert db.execute("SELECT count(*) FROM files").fetchone()[0] == 1


def test_files_on_an_unmounted_filesystem_are_not_pruned(tmp_path: Path):
    """An offline mount reports ENOENT like a deletion; only the device tells them apart."""
    notes = tmp_path / "notes.txt"
    notes.write_text("The engine runs.\n")
    index = build_index(tmp_path / "index.sqlite3")
    index.index(str(tmp_path))

    real_stat = semantic.os.stat
    stored = tmp_path.stat().st_dev

    def unmounted_stat(target, *args, **kwargs):
        # The mountpoint is back on the host filesystem, so its device differs.
        result = real_stat(target, *args, **kwargs)
        return mock.Mock(st_dev=stored + 1) if Path(target) == tmp_path else result

    with semantic._connect(tmp_path / "index.sqlite3") as db:
        with mock.patch.object(
            semantic.os, "lstat", side_effect=FileNotFoundError(errno.ENOENT, "gone")
        ), mock.patch.object(semantic.os, "stat", side_effect=unmounted_stat):
            removed = index._prune_removed(db, tmp_path, set())

    assert removed == 0
    with sqlite3.connect(tmp_path / "index.sqlite3") as db:
        assert db.execute("SELECT count(*) FROM files").fetchone()[0] == 1


def test_index_records_the_device_for_each_file(tmp_path: Path):
    (tmp_path / "notes.txt").write_text("The engine runs.\n")
    index = build_index(tmp_path / "index.sqlite3")
    index.index(str(tmp_path))

    with sqlite3.connect(tmp_path / "index.sqlite3") as db:
        assert db.execute("SELECT device FROM files").fetchone()[0] == tmp_path.stat().st_dev


def test_genuinely_deleted_files_are_still_pruned(tmp_path: Path):
    notes = tmp_path / "notes.txt"
    notes.write_text("The engine runs.\n")
    index = build_index(tmp_path / "index.sqlite3")
    index.index(str(tmp_path))
    notes.unlink()

    with semantic._connect(tmp_path / "index.sqlite3") as db:
        assert index._prune_removed(db, tmp_path, set()) == 1


def test_skip_dirs_still_apply_below_the_root(tmp_path: Path):
    project = tmp_path / "project"
    (project / "node_modules").mkdir(parents=True)
    (project / "node_modules" / "vendor.js").write_text("module.exports = 1\n")
    (project / "app.js").write_text("console.log(1)\n")

    assert [path.name for path in iter_text_files(project)] == ["app.js"]


def test_index_warns_when_nothing_is_eligible(tmp_path: Path):
    empty = tmp_path / "empty"
    empty.mkdir()
    (empty / "photo.raw").write_text("not indexable\n")

    result = build_index(tmp_path / "index.sqlite3").index(str(empty))
    assert result["files_seen"] == 0
    assert "No indexable files found" in result["warning"]


def test_root_filter_does_not_treat_underscores_as_wildcards(tmp_path: Path):
    project = tmp_path / "project"
    (project / "a_b").mkdir(parents=True)
    (project / "axb").mkdir(parents=True)
    (project / "a_b" / "one.py").write_text("engine\n")
    (project / "axb" / "two.py").write_text("engine\n")
    index = build_index(tmp_path / "index.sqlite3")
    index.index(str(project))

    hits = index.search("engine", limit=10, root=str(project / "a_b"))
    assert [Path(hit["path"]).name for hit in hits] == ["one.py"]


def test_deleted_files_are_pruned_on_reindex(tmp_path: Path):
    documents = tmp_path / "documents"
    documents.mkdir()
    keep = documents / "keep.txt"
    remove = documents / "remove.txt"
    keep.write_text("The engine is here.\n")
    remove.write_text("The engine is also here.\n")
    index = build_index(tmp_path / "index.sqlite3")
    index.index(str(documents))
    assert index.status()["files"] == 2

    remove.unlink()
    result = index.index(str(documents))

    assert result["files_removed"] == 1
    assert index.status()["files"] == 1
    assert all(not hit["path"].endswith("remove.txt") for hit in index.search("engine", limit=10))


@pytest.mark.parametrize("parent_first", [True, False])
def test_overlapping_roots_prune_deletions_in_either_indexing_order(tmp_path: Path, parent_first):
    """Pruning must not depend on which root happened to record a file last."""
    project = tmp_path / "project"
    nested = project / "sub"
    nested.mkdir(parents=True)
    (project / "top.txt").write_text("engine top\n")
    doomed = nested / "gone.txt"
    doomed.write_text("engine nested\n")
    index = build_index(tmp_path / "index.sqlite3")
    for root in (project, nested) if parent_first else (nested, project):
        index.index(str(root))

    doomed.unlink()
    result = index.index(str(nested))

    assert result["files_removed"] == 1
    assert all(not hit["path"].endswith("gone.txt") for hit in index.search("engine", limit=10))
    assert index.status()["files"] == 1


def test_reindexing_a_deleted_single_file_root_removes_it(tmp_path: Path):
    """Re-indexing the path is the only handle a user has on a deleted file."""
    notes = tmp_path / "notes.txt"
    notes.write_text("The engine runs.\n")
    index = build_index(tmp_path / "index.sqlite3")
    index.index(str(notes))
    assert index.status()["files"] == 1

    notes.unlink()
    result = index.index(str(notes))

    assert result["files_removed"] == 1
    assert "no longer exists" in result["removed_root"]
    assert index.status()["files"] == 0
    assert index.search("engine", limit=10) == []


def test_reindexing_a_deleted_directory_root_removes_its_files(tmp_path: Path):
    documents = tmp_path / "documents"
    documents.mkdir()
    (documents / "one.txt").write_text("engine one\n")
    (documents / "two.txt").write_text("engine two\n")
    index = build_index(tmp_path / "index.sqlite3")
    index.index(str(documents))

    shutil.rmtree(documents)
    result = index.index(str(documents))

    assert result["files_removed"] == 2
    assert index.status()["files"] == 0


def test_indexing_a_path_that_was_never_indexed_still_fails(tmp_path: Path):
    index = build_index(tmp_path / "index.sqlite3")
    with pytest.raises(ValueError, match="Path does not exist"):
        index.index(str(tmp_path / "nowhere"))


def test_pruning_never_removes_a_file_that_still_exists(tmp_path: Path):
    """Excluded directories are not traversed, so existence is what decides."""
    project = tmp_path / "project"
    excluded = project / "node_modules"
    excluded.mkdir(parents=True)
    (project / "app.js").write_text("engine\n")
    (excluded / "vendor.js").write_text("engine\n")
    index = build_index(tmp_path / "index.sqlite3")
    index.index(str(excluded))
    assert index.index(str(project))["files_removed"] == 0

    assert index.status()["files"] == 2
    assert any(hit["path"].endswith("vendor.js") for hit in index.search("engine", limit=10))


def test_pruning_is_scoped_to_the_indexed_root(tmp_path: Path):
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (first / "one.txt").write_text("engine\n")
    (second / "two.txt").write_text("engine\n")
    index = build_index(tmp_path / "index.sqlite3")
    index.index(str(first))
    index.index(str(second))

    assert index.index(str(first))["files_removed"] == 0
    assert index.status()["files"] == 2


def test_connections_are_closed(tmp_path: Path, monkeypatch):
    opened = []
    real_connect = sqlite3.connect

    def spy(*args, **kwargs):
        connection = real_connect(*args, **kwargs)
        opened.append(connection)
        return connection

    monkeypatch.setattr(sqlite3, "connect", spy)
    index = build_index(tmp_path / "index.sqlite3")
    index.status()
    index.status()

    assert len(opened) == 2
    for connection in opened:
        with pytest.raises(sqlite3.ProgrammingError):
            connection.execute("SELECT 1")


def test_unmodified_files_are_rechunked_when_the_chunker_changes(tmp_path: Path, monkeypatch):
    documents = tmp_path / "documents"
    documents.mkdir()
    (documents / "notes.txt").write_text("The engine runs.\n")
    db_path = tmp_path / "index.sqlite3"
    build_index(db_path).index(str(documents))

    monkeypatch.setattr(semantic, "CHUNKER_VERSION", "999")
    result = build_index(db_path).index(str(documents))

    assert result["files_rechunked"] == 1
    assert result["files_unchanged"] == 0
    assert "rebuilt" in result
    assert build_index(db_path).status()["chunks"] == 1


def test_a_chunker_change_leaves_other_roots_intact(tmp_path: Path, monkeypatch):
    """Indexing one root must never delete another root's passages."""
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (first / "one.txt").write_text("The engine starts.\n")
    (second / "two.txt").write_text("The engine stops.\n")
    db_path = tmp_path / "index.sqlite3"
    build_index(db_path).index(str(first))
    build_index(db_path).index(str(second))

    monkeypatch.setattr(semantic, "CHUNKER_VERSION", "999")
    build_index(db_path).index(str(first))

    status = build_index(db_path).status()
    assert status["files"] == 2
    assert str(second) in status["roots"]
    hits = build_index(db_path).search("engine", limit=10)
    assert any(hit["path"].endswith("two.txt") for hit in hits)


def test_a_database_without_the_chunker_column_is_migrated(tmp_path: Path):
    """0.2.0 databases predate the column, so opening one must not raise."""
    documents = tmp_path / "documents"
    documents.mkdir()
    (documents / "notes.txt").write_text("The engine runs.\n")
    db_path = tmp_path / "index.sqlite3"
    build_index(db_path).index(str(documents))
    with sqlite3.connect(db_path) as db:
        db.execute("ALTER TABLE files DROP COLUMN chunker")

    result = build_index(db_path).index(str(documents))

    assert result["files_rechunked"] == 1
    assert result["files_updated"] == 1
    assert build_index(db_path).status()["chunks"] == 1


def test_a_fresh_database_is_not_reported_as_rebuilt(tmp_path: Path):
    documents = tmp_path / "documents"
    documents.mkdir()
    (documents / "notes.txt").write_text("The engine runs.\n")

    result = build_index(tmp_path / "index.sqlite3").index(str(documents))
    assert result["files_rechunked"] == 0
    assert "rebuilt" not in result


class FakeRerank:
    """Ranks by keyword count, the reverse of FakePipeline's cosine order."""

    last_texts: list[str] = []

    def rerank(self, query, texts):
        FakeRerank.last_texts = list(texts)
        scored = [(index, float(text.lower().count("engine"))) for index, text in enumerate(texts)]
        return sorted(scored, key=lambda pair: pair[1], reverse=True)


def build_reranking_index(db_path: Path) -> SemanticIndex:
    return SemanticIndex(db_path, pipeline_factory=FakePipeline, rerank_factory=FakeRerank)


def _corpus(tmp_path: Path) -> Path:
    root = tmp_path / "corpus"
    root.mkdir()
    for number in range(30):
        engines = "engine " * (number % 5)
        (root / f"doc{number:02d}.txt").write_text(
            f"apple network notes {number}\n{engines}\ntrailing line {number}\n", encoding="utf-8"
        )
    return root


def test_reranking_reorders_and_annotates(tmp_path):
    """A reranked hit must be identifiable without the return type changing."""
    index = build_reranking_index(tmp_path / "db.sqlite3")
    index.index(str(_corpus(tmp_path)))
    results = index.search("engine", limit=5, rerank=True)
    assert all("rerank_score" in hit for hit in results)
    assert all("score" in hit for hit in results)
    scores = [hit["rerank_score"] for hit in results]
    assert scores == sorted(scores, reverse=True)


def test_reranking_sees_at_most_the_candidate_ceiling(tmp_path):
    """Cost must stay bounded no matter how large the index grows."""
    index = build_reranking_index(tmp_path / "db.sqlite3")
    index.index(str(_corpus(tmp_path)))
    index.search("engine", limit=5, rerank=True)
    assert len(FakeRerank.last_texts) <= semantic.RERANK_CANDIDATES


def test_rerank_result_count_respects_limit(tmp_path):
    index = build_reranking_index(tmp_path / "db.sqlite3")
    index.index(str(_corpus(tmp_path)))
    assert len(index.search("engine", limit=3, rerank=True)) == 3


def test_rerank_true_without_a_model_is_an_explicit_error(tmp_path, monkeypatch):
    """Asking for a missing model must not silently degrade to plain search."""
    monkeypatch.setattr(semantic, "RERANK_MODEL", tmp_path / "absent")
    monkeypatch.setattr("intel_npu_tools.rerank.RERANK_MODEL", tmp_path / "absent")
    index = build_index(tmp_path / "db.sqlite3")
    index.index(str(_corpus(tmp_path)))
    with pytest.raises(FileNotFoundError, match="--with-reranker"):
        index.search("engine", rerank=True)


def test_search_without_a_reranker_is_unchanged(tmp_path, monkeypatch):
    monkeypatch.setattr("intel_npu_tools.rerank.RERANK_MODEL", tmp_path / "absent")
    index = build_index(tmp_path / "db.sqlite3")
    index.index(str(_corpus(tmp_path)))
    results = index.search("engine", limit=4)
    assert results and all("rerank_score" not in hit for hit in results)


def test_rerank_false_never_constructs_the_pipeline(tmp_path):
    """Opting out must not pay the compile cost of a model it will not use."""

    def explode():
        raise AssertionError("the reranker was constructed despite rerank=False")

    index = SemanticIndex(
        tmp_path / "db.sqlite3", pipeline_factory=FakePipeline, rerank_factory=explode
    )
    index.index(str(_corpus(tmp_path)))
    assert index.search("engine", limit=3, rerank=False)


def test_reranking_an_empty_index_returns_nothing(tmp_path):
    """rerank(query, []) would be a wasted compile and a confusing call."""

    def explode():
        raise AssertionError("the reranker was constructed for an empty result set")

    index = SemanticIndex(
        tmp_path / "db.sqlite3", pipeline_factory=FakePipeline, rerank_factory=explode
    )
    assert index.search("engine", limit=3) == []


def test_reranking_is_off_unless_asked_for(tmp_path):
    """Measured on this repo the cross-encoder hurts as often as it helps, so
    having the model installed must not silently change every search."""

    def explode():
        raise AssertionError("the reranker ran without being requested")

    index = SemanticIndex(
        tmp_path / "db.sqlite3", pipeline_factory=FakePipeline, rerank_factory=explode
    )
    index.index(str(_corpus(tmp_path)))
    results = index.search("engine", limit=3)
    assert results and all("rerank_score" not in hit for hit in results)
