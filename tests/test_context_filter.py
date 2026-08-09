"""Cover the token-saving file filter.

The load-bearing promise of this tool is that every span it returns is copied
byte for byte out of the file at the line numbers it reports. An agent that
cites a span it cannot trust is worse than one that read the whole file, so the
verbatim property is asserted directly rather than inferred.
"""

import numpy as np
import pytest

from intel_npu_tools import context_filter
from intel_npu_tools.context_filter import filter_context


class FakePipeline:
    """Scores on keyword counts, so the expected ranking is obvious by eye."""

    def _vector(self, text):
        lowered = text.lower()
        vector = np.array([
            lowered.count("linker"), lowered.count("warning"), lowered.count("cache"), 1.0
        ], dtype=np.float32)
        return (vector / np.linalg.norm(vector)).tolist()

    def embed_documents(self, texts):
        return [self._vector(text) for text in texts]

    def embed_query(self, text):
        return self._vector(text)


@pytest.fixture(autouse=True)
def clear_cache():
    context_filter._cache.clear()
    context_filter._cache_order.clear()
    yield
    context_filter._cache.clear()
    context_filter._cache_order.clear()


def write_log(tmp_path, needle_line=400, total=900):
    lines = [f"[{n:04d}] routine build step producing ordinary output" for n in range(total)]
    lines[needle_line] = "[0400] fatal error: linker linker linker could not resolve symbol"
    path = tmp_path / "build.log"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path, lines


def run(path, query="why did the linker step fail", **kwargs):
    return filter_context(str(path), query, pipeline_factory=FakePipeline, **kwargs)


def test_returns_spans_copied_verbatim_from_the_file(tmp_path):
    """A span that is not a byte-exact quote makes every citation untrustworthy."""
    path, lines = write_log(tmp_path)
    result = run(path)
    for span in result["spans"]:
        expected = "\n".join(lines[span["start_line"] - 1:span["end_line"]])
        assert span["text"] == expected


def test_line_numbers_locate_the_quoted_text(tmp_path):
    path, lines = write_log(tmp_path)
    result = run(path)
    for span in result["spans"]:
        assert lines[span["start_line"] - 1] == span["text"].split("\n")[0]
        assert lines[span["end_line"] - 1] == span["text"].split("\n")[-1]


def test_the_relevant_line_is_actually_found(tmp_path):
    path, _ = write_log(tmp_path)
    result = run(path)
    assert any("could not resolve symbol" in span["text"] for span in result["spans"])


def test_chunk_accounting_is_complete(tmp_path):
    """Silent truncation reads as full coverage, so the arithmetic must close."""
    path, _ = write_log(tmp_path)
    result = run(path, limit=3)
    assert result["dropped"]["chunks"] + 3 == result["input"]["chunks"]


def test_dropped_note_reports_the_score_gap(tmp_path):
    path, _ = write_log(tmp_path)
    result = run(path, limit=2)
    assert result["dropped"]["chunks"] > 0
    assert len(result["dropped"]["score_range"]) == 2
    assert "Raise limit" in result["dropped"]["note"]


def test_output_is_smaller_than_the_input(tmp_path):
    path, _ = write_log(tmp_path)
    result = run(path, limit=3)
    assert result["returned"]["estimated_tokens"] < result["input"]["estimated_tokens"]
    assert result["returned"]["estimated_tokens_saved"] > 0


def test_spans_come_back_in_document_order(tmp_path):
    """Score order shuffles a log into nonsense; readers need it in file order."""
    path, _ = write_log(tmp_path)
    starts = [span["start_line"] for span in run(path, limit=6)["spans"]]
    assert starts == sorted(starts)


def test_overlapping_spans_are_merged(tmp_path):
    path, _ = write_log(tmp_path)
    spans = run(path, limit=20)["spans"]
    for earlier, later in zip(spans, spans[1:]):
        assert later["start_line"] > earlier["end_line"] + 1


def test_context_lines_widen_the_span(tmp_path):
    path, _ = write_log(tmp_path)
    narrow = run(path, limit=1)["spans"][0]
    wide = run(path, limit=1, context_lines=5)["spans"][0]
    assert wide["start_line"] <= narrow["start_line"]
    assert wide["end_line"] >= narrow["end_line"]


def test_context_lines_stay_inside_the_file(tmp_path):
    path, lines = write_log(tmp_path)
    for span in run(path, limit=20, context_lines=10_000)["spans"]:
        assert span["start_line"] >= 1
        assert span["end_line"] <= len(lines)


def test_tiny_files_are_refused(tmp_path):
    """Filtering a small file costs more tokens than reading it."""
    path = tmp_path / "small.log"
    path.write_text("too short to be worth filtering", encoding="utf-8")
    with pytest.raises(ValueError, match="cost"):
        run(path)


def test_huge_files_are_refused_with_advice(tmp_path):
    path = tmp_path / "huge.log"
    path.write_text("x" * (context_filter.MAX_INPUT_BYTES + 1), encoding="utf-8")
    with pytest.raises(ValueError, match="grep"):
        run(path)


def test_missing_file_is_refused(tmp_path):
    with pytest.raises(ValueError, match="Not a file"):
        run(tmp_path / "absent.log")


def test_empty_query_is_refused(tmp_path):
    path, _ = write_log(tmp_path)
    with pytest.raises(ValueError, match="empty"):
        run(path, query="   ")


def test_limit_is_clamped(tmp_path):
    path, _ = write_log(tmp_path)
    assert len(run(path, limit=10_000)["spans"]) <= context_filter.MAX_LIMIT
    assert run(path, limit=0)["spans"]


def test_undecodable_bytes_do_not_crash(tmp_path):
    """Build logs routinely carry stray non-UTF-8 bytes."""
    path = tmp_path / "binary.log"
    path.write_bytes(b"linker error\n" + b"\xff\xfe" * 4000 + b"\nlinker again\n")
    assert run(path)["spans"]


def test_repeated_calls_reuse_cached_vectors(tmp_path):
    """Agents ask several questions of one log; re-embedding it each time is the cost."""
    path, _ = write_log(tmp_path)
    calls = {"n": 0}

    class CountingPipeline(FakePipeline):
        def embed_documents(self, texts):
            calls["n"] += len(texts)
            return super().embed_documents(texts)

    filter_context(str(path), "linker", pipeline_factory=CountingPipeline)
    after_first = calls["n"]
    filter_context(str(path), "warning", pipeline_factory=CountingPipeline)
    assert after_first > 0
    assert calls["n"] == after_first


def test_cache_is_bounded(tmp_path):
    for index in range(context_filter._CACHE_ENTRIES + 3):
        path = tmp_path / f"log{index}.log"
        path.write_text("\n".join(f"line {index} number {n} linker" for n in range(400)), encoding="utf-8")
        run(path)
    assert len(context_filter._cache) <= context_filter._CACHE_ENTRIES


def test_nothing_is_written_to_the_semantic_index(tmp_path):
    """This is a stateless tool; polluting the index would confuse its status report."""
    from intel_npu_tools.paths import SEMANTIC_DB

    path, _ = write_log(tmp_path)
    before = SEMANTIC_DB.stat().st_mtime_ns if SEMANTIC_DB.exists() else None
    run(path)
    after = SEMANTIC_DB.stat().st_mtime_ns if SEMANTIC_DB.exists() else None
    assert before == after


def test_context_lines_cannot_produce_overlapping_spans(tmp_path):
    """Widening after merging let spans grow back into each other.

    Found by review, not by the merge test above, which only ever ran at the
    default context_lines of zero. Over a 600-line file at context_lines=200
    the reply repeated 154 lines and reported 754 lines returned.
    """
    path, lines = write_log(tmp_path, needle_line=100, total=600)
    lines[400] = "[0400] a second linker linker failure"
    path.write_text("\n".join(lines), encoding="utf-8")
    for context_lines in (0, 60, 120, 200, 5000):
        result = run(path, limit=2, context_lines=context_lines)
        spans = result["spans"]
        for earlier, later in zip(spans, spans[1:]):
            assert later["start_line"] > earlier["end_line"], context_lines
        covered = {
            number
            for span in spans
            for number in range(span["start_line"], span["end_line"] + 1)
        }
        assert result["returned"]["lines"] == len(covered), context_lines


def test_reported_line_count_never_exceeds_the_file(tmp_path):
    """Double-counted lines showed up here first as a count larger than the file."""
    path, lines = write_log(tmp_path, total=600)
    result = run(path, limit=8, context_lines=500)
    assert result["returned"]["lines"] <= len(lines)
