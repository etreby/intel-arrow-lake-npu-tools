"""Return only the parts of a large text file that answer a question.

This exists to keep tokens out of an AI agent's context window. Reading a
two-thousand-line test log to find one failure is the most ordinary way an
agent exhausts its context, and almost all of those tokens are never needed
again. Embedding the file locally and returning a handful of spans moves that
work onto the NPU, where it costs the agent nothing.

Everything returned is copied verbatim out of the file. Nothing here generates
text, so quoted lines and the line numbers beside them can be trusted and cited.
That guarantee is the reason this module does not summarise, and the reason a
local language model is a poor fit for the job.
"""

import hashlib
import threading
from pathlib import Path

import numpy as np

from .semantic import chunk_text, embedding_pipeline


# Below this a file is cheaper to read outright than to describe: the reply,
# its metadata, and the agent's own tool call already cost about as much.
MIN_INPUT_BYTES = 4 * 1024
# Above this the wait stops being worth it. Embedding is roughly 0.25 seconds
# per 1200-character chunk, so 256 KB is already the better part of a minute,
# and several MCP clients give up on a tool call at thirty to sixty seconds.
MAX_INPUT_BYTES = 256 * 1024
MAX_LIMIT = 20
# Rough, and labelled as such everywhere it surfaces. Four characters per token
# holds for prose and ordinary code; hex digests, base64 blobs, and minified
# JSON tokenise far worse, so treat this as plus or minus thirty percent.
CHARS_PER_TOKEN = 4

# Agents usually ask two or three questions of the same log, and re-embedding it
# each time is the difference between a fifth of a second and twenty seconds.
_CACHE_ENTRIES = 4
_cache: dict[str, list] = {}
_cache_order: list[str] = []
_cache_lock = threading.RLock()


def _estimate_tokens(chars: int) -> int:
    return chars // CHARS_PER_TOKEN


def _read(path: Path) -> str:
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_file():
        raise ValueError(f"Not a file: {resolved}")
    size = resolved.stat().st_size
    if size < MIN_INPUT_BYTES:
        raise ValueError(
            f"{resolved} is {size} bytes. Files under {MIN_INPUT_BYTES} bytes cost "
            "fewer tokens to read directly than to filter."
        )
    if size > MAX_INPUT_BYTES:
        raise ValueError(
            f"{resolved} is {size} bytes, over the {MAX_INPUT_BYTES}-byte limit. "
            "Narrow it with grep first, then filter the result."
        )
    # Build logs carry ANSI escapes and stray non-UTF-8 bytes; replacing them
    # degrades relevance for those chunks but keeps the rest of the file usable.
    return resolved.read_text(encoding="utf-8", errors="replace")


def _vectors_for(text: str, pipe) -> list:
    """Chunk and embed, reusing the last few files' vectors."""
    key = hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()
    with _cache_lock:
        cached = _cache.get(key)
    if cached is not None:
        return cached
    pieces = chunk_text(text)
    # pad_to_max_length fixes the pipeline's batch at one, so these are embedded
    # one at a time by necessity rather than by choice.
    entries = [
        (start, end, content, np.asarray(pipe.embed_documents([content])[0], dtype=np.float32))
        for start, end, content in pieces
    ]
    with _cache_lock:
        _cache[key] = entries
        _cache_order.append(key)
        while len(_cache_order) > _CACHE_ENTRIES:
            _cache.pop(_cache_order.pop(0), None)
    return entries


def _merge(spans: list[dict]) -> list[dict]:
    """Join spans whose line ranges touch, keeping the best score.

    Chunks overlap by two lines, so neighbouring winners would otherwise repeat
    those lines and read as duplicated output.
    """
    merged: list[dict] = []
    for span in sorted(spans, key=lambda item: item["start_line"]):
        if merged and span["start_line"] <= merged[-1]["end_line"] + 1:
            previous = merged[-1]
            previous["end_line"] = max(previous["end_line"], span["end_line"])
            previous["score"] = max(previous["score"], span["score"])
        else:
            merged.append(dict(span))
    return merged


def filter_context(
    path: str,
    query: str,
    limit: int = 8,
    context_lines: int = 0,
    pipeline_factory=embedding_pipeline,
) -> dict:
    """Rank a file's chunks against a query and return the best spans verbatim."""
    query = query.strip()
    if not query:
        raise ValueError("Query cannot be empty")
    limit = max(1, min(int(limit), MAX_LIMIT))
    context_lines = max(0, int(context_lines))

    resolved = Path(path).expanduser().resolve()
    text = _read(resolved)
    lines = text.splitlines()

    pipe = pipeline_factory()
    entries = _vectors_for(text, pipe)
    if not entries:
        raise ValueError(f"{resolved} contains no indexable text")

    query_vector = np.asarray(pipe.embed_query(query), dtype=np.float32)
    scored = []
    for start, end, _content, vector in entries:
        if vector.size != query_vector.size:
            continue
        # config.normalize is on, so the dot product is already the cosine.
        scored.append({
            "start_line": start,
            "end_line": end,
            "score": round(float(np.dot(query_vector, vector)), 6),
        })
    scored.sort(key=lambda item: item["score"], reverse=True)

    kept, dropped = scored[:limit], scored[limit:]
    # Widen first, then merge. Merging before widening leaves spans that are
    # disjoint only until context_lines pushes them back into each other, and
    # the reply then repeats those lines in two spans and counts them twice: at
    # context_lines=200 over a 600-line file this reported 754 lines returned.
    widened = [
        {
            "start_line": max(1, span["start_line"] - context_lines),
            "end_line": min(len(lines), span["end_line"] + context_lines),
            "score": span["score"],
        }
        for span in _merge(kept)
    ]
    spans = [
        {
            "start_line": span["start_line"],
            "end_line": span["end_line"],
            "score": span["score"],
            "text": "\n".join(lines[span["start_line"] - 1:span["end_line"]]),
        }
        for span in _merge(widened)
    ]

    returned_chars = sum(len(span["text"]) for span in spans)
    input_tokens = _estimate_tokens(len(text))
    returned_tokens = _estimate_tokens(returned_chars)
    note = (
        f"{len(dropped)} of {len(scored)} chunks were not returned."
        if dropped
        else "Every chunk was returned."
    )
    if dropped and kept:
        note += (
            f" Their best score was {max(item['score'] for item in dropped):.3f} against "
            f"{min(item['score'] for item in kept):.3f} for the weakest span kept. Raise "
            "limit or refine the query if that gap looks too close to trust."
        )

    return {
        "path": str(resolved),
        "query": query,
        "device": "NPU",
        "ranking": "embedding",
        "input": {
            "bytes": len(text.encode("utf-8", errors="replace")),
            "lines": len(lines),
            "chunks": len(scored),
            "estimated_tokens": input_tokens,
        },
        "returned": {
            "spans": len(spans),
            "lines": sum(span["end_line"] - span["start_line"] + 1 for span in spans),
            "chars": returned_chars,
            "estimated_tokens": returned_tokens,
            "estimated_tokens_saved": max(0, input_tokens - returned_tokens),
            "reduction": (
                f"{round(100 * (1 - returned_tokens / input_tokens))}%" if input_tokens else "0%"
            ),
        },
        "dropped": {
            "chunks": len(dropped),
            "score_range": (
                [min(item["score"] for item in dropped), max(item["score"] for item in dropped)]
                if dropped
                else []
            ),
            "note": note,
        },
        "estimates": (
            "Token counts are approximate, from a four-characters-per-token rule. "
            "Content such as hex digests or base64 tokenises far worse."
        ),
        "spans": spans,
    }
