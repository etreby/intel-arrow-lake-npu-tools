from pathlib import Path

import numpy as np

from intel_npu_tools.semantic import SemanticIndex, chunk_text


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


def test_chunk_text_tracks_lines():
    chunks = chunk_text("one\ntwo\nthree\nfour", target_chars=7, overlap_lines=1)
    assert chunks[0] == (1, 2, "one\ntwo")
    assert chunks[-1][1] == 4


def test_index_and_semantic_search(tmp_path: Path):
    documents = tmp_path / "documents"
    documents.mkdir()
    (documents / "fruit.txt").write_text("Apples and pears are fruit.\n")
    (documents / "code.md").write_text("The rendering engine initializes the network.\n")
    index = SemanticIndex(tmp_path / "index.sqlite3", pipeline_factory=FakePipeline)

    result = index.index(str(documents))
    assert result["files_updated"] == 2
    assert result["chunks_added"] == 2
    assert index.index(str(documents))["files_unchanged"] == 2

    hits = index.search("engine", limit=1)
    assert hits[0]["path"].endswith("code.md")
    assert hits[0]["start_line"] == 1
    assert index.status()["files"] == 2
