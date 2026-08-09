"""Cross-encoder reranking on the NPU.

Embedding search is a bi-encoder: the query and each passage are turned into
vectors independently, so it retrieves on topical similarity and is weak at the
question that actually matters, which of these five similar-looking passages is
the one being asked about. A cross-encoder reads the query and the passage
together in one pass and scores the pair, which is markedly better at that
discrimination and markedly slower. The usual arrangement, and the one used
here, is to retrieve a shortlist cheaply and re-score only the shortlist.

This does not use openvino_genai's TextRerankPipeline. That pipeline pads the
tokenized input but never reshapes the graph, and the model ships with fully
dynamic axes, so the NPU compiler rejects it outright with "Got negative shape
dim bound: '-1'". Reshaping the model to a static window first, as ocr.py
already does for its two models, compiles in a few seconds and runs at about
48 milliseconds per pair.
"""

import json
import threading

import numpy as np

from .paths import RERANK_MODEL
from .runtime import npu_properties


# The window covers the query and the passage together, so a long query eats
# into the passage's share. XLM-RoBERTa cannot exceed 512 in any case: its
# max_position_embeddings is 514, including the two sentinel positions. This is
# baked into the compiled model, so changing it forces a recompile.
MAX_LENGTH = 512
DEFAULT_PAD_TOKEN_ID = 1

_reranker = None
_lock = threading.RLock()


class NpuReranker:
    """Scores (query, passage) pairs on the NPU with a statically shaped model."""

    def __init__(self, model_dir=RERANK_MODEL, max_length: int = MAX_LENGTH):
        import openvino as ov

        # Registers the extension opset the tokenizer IR is built from. Without
        # it read_model fails with "Cannot create SpecialTokensSplit layer ...
        # from unsupported opset: extension".
        import openvino_tokenizers  # noqa: F401

        self.max_length = max_length
        core = ov.Core()
        model = core.read_model(model_dir / "openvino_model.xml")
        model.reshape({
            "input_ids": ov.PartialShape([1, max_length]),
            "attention_mask": ov.PartialShape([1, max_length]),
        })
        self._model = core.compile_model(model, "NPU", npu_properties())
        # Tokenization is string preprocessing, not inference, and there is no
        # NPU implementation of it. Running it on the CPU is not the CPU
        # fallback that docs/TROUBLESHOOTING.md warns against; the scoring model
        # itself still runs, and only runs, on the NPU.
        self._tokenizer = core.compile_model(
            core.read_model(model_dir / "openvino_tokenizer.xml"), "CPU"
        )
        self._pad_token_id = self._read_pad_token_id(model_dir)

    @staticmethod
    def _read_pad_token_id(model_dir) -> int:
        try:
            config = json.loads((model_dir / "config.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return DEFAULT_PAD_TOKEN_ID
        value = config.get("pad_token_id", DEFAULT_PAD_TOKEN_ID)
        return int(value) if isinstance(value, int) else DEFAULT_PAD_TOKEN_ID

    def _encode(self, query: str, passage: str):
        # </s></s> is the sentence-pair separator this tokenizer was trained
        # with, so the model sees a pair rather than one run-on string.
        tokens = self._tokenizer([f"{query}</s></s>{passage}"])
        raw = tokens[self._tokenizer.output("input_ids")][0]
        used = min(self.max_length, len(raw))
        input_ids = np.full(self.max_length, self._pad_token_id, dtype=np.int64)
        input_ids[:used] = raw[:used]
        attention_mask = np.zeros(self.max_length, dtype=np.int64)
        attention_mask[:used] = 1
        return input_ids.reshape(1, -1), attention_mask.reshape(1, -1)

    def rerank(self, query: str, texts) -> list[tuple[int, float]]:
        """Return (original index, score) pairs, best first.

        Scores are unbounded logits. They are not cosine similarities and must
        never be compared against one, nor read as a probability.
        """
        scored = []
        for index, passage in enumerate(texts):
            input_ids, attention_mask = self._encode(query, passage)
            output = self._model([input_ids, attention_mask])
            scored.append((index, float(output[self._model.output(0)][0][0])))
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored


def rerank_pipeline():
    """Compile the reranker once per process."""
    global _reranker
    with _lock:
        if _reranker is None:
            if not RERANK_MODEL.is_dir():
                raise FileNotFoundError(
                    f"Reranker model not found at {RERANK_MODEL}; run "
                    "scripts/download-models.py --with-reranker"
                )
            _reranker = NpuReranker()
        return _reranker


def available() -> bool:
    return _reranker is not None or RERANK_MODEL.is_dir()
