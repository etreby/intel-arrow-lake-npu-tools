---
name: intel-npu-local-knowledge
description: Index and semantically search private local text, source code, documentation, and logs with the intel-npu-tools MCP server. Use when an agent needs meaning-based retrieval from a local project or document directory, needs to refresh an existing NPU index, or needs source-backed local context without uploading files.
---

# Intel NPU Local Knowledge

Use the `intel-npu-tools` MCP server to retrieve relevant local passages. Keep indexed scope explicit and cite returned paths and line numbers.

## Workflow

1. Call `semantic_index_status` to inspect existing roots.
2. If the requested file or directory is absent or may have changed, ask for its path when unknown, then call `semantic_index` once. Index only the scope relevant to the task.
3. Call `semantic_search` with a specific natural-language query. Pass `root` when results must stay within one indexed tree. Start with `limit=5`.
4. Answer from the returned passages and cite each local path with its starting line. Distinguish retrieved facts from inference.
5. Refine the query when results are weak or ambiguous. Do not repeatedly re-index unchanged content; indexing is incremental.

## Tool guidance

- `semantic_index(path)`: Index one supported text file or recursively index a directory on the Intel NPU.
- `semantic_search(query, limit, root)`: Return ranked passages with similarity score, path, line range, and text.
- `semantic_index_status()`: Return database location, roots, file count, and chunk count.

Treat scores as ranking signals, not calibrated probabilities. Prefer passages that directly address the query and verify critical details against the cited file when a file-reading tool is available.

## Privacy and boundaries

- Index only paths the user placed in scope.
- Do not index credential stores, browser profiles, key directories, or unrelated home folders.
- Local text chunks and embeddings persist in the SQLite index until the toolkit data directory is removed.
- The MCP transport is local stdio; no indexed text is uploaded by this toolkit.
