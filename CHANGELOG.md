# Changelog

## 0.2.1 - 2026-08-09

### Fixed

- Excluded directory names are matched only below the indexed root. Previously any ancestor named `build`, `dist`, `models`, or `venv` made a whole tree unindexable, and `index` reported zero files without explanation.
- `models` was removed from the exclusion list, which only hid legitimate source directories. Model directories are now recognised by the weights they contain (`.bin`, `.gguf`, `.onnx`, `.pt`, `.pth`, `.safetensors`) and pruned whole, so a source directory named `models/` is indexed while a Whisper or OpenVINO directory is not. Weights were always excluded by extension, but the text sidecars beside them were not: tokenizer vocabularies, merge tables, and OpenVINO IR graphs are `.json`, `.txt`, and `.xml`, and added megabytes of machine-generated data to every search.
- Cache directories are excluded: `.cache`, `.ipynb_checkpoints`, `.mypy_cache`, `.pytest_cache`, and `.ruff_cache`.
- `--root` and `semantic_search(root=...)` escape SQL `LIKE` wildcards. A path containing `_` or `%` previously matched sibling directories and returned passages from outside the requested scope.
- SQLite connections are closed instead of only committed, so the long-lived MCP server no longer accumulates handles and WAL files.
- Re-indexing a root now removes entries for files deleted from disk. Searches previously kept returning passages from paths that no longer existed. A row is dropped only when its file is genuinely gone, never because a traversal skipped it, so overlapping and nested roots can be indexed in any order without erasing each other. Indexing a path that has since been deleted now removes its entries instead of failing, which is the only way a user could drop one. "Gone" means `lstat` reports `ENOENT` or `ENOTDIR` *and* the recorded device still matches the nearest existing ancestor, so neither a permission error nor an unmounted disk can erase entries for files that are still there — an `os.path.exists` check would have erased both. Each file's device is recorded for this purpose; 0.2.0 databases gain the column automatically and fall back to the old check until their next index run.
- Chunks are capped so their tails are not silently dropped by the 512-token embedding limit, and an overlong single line is split rather than truncated. The chunker version is recorded per file, so indexing a root re-chunks that root's files while leaving every other indexed root intact.
- OCR no longer fails when Tesseract is missing or errors; it falls back to the NPU recognizer as documented.
- `__version__` is derived from package metadata instead of drifting from `pyproject.toml`.
- Closing the speech application mid-recording removes its temporary WAV file.

### Security

- The Level Zero loader `.deb`, which is unsigned on its PPA snapshot path, is pinned by SHA-256 and verified before installation.
- The driver installer verifies a detached signature for every package it installs, and installs exactly the packages it verified. It previously required only that some signature in the archive was valid, so a package shipped without its `.asc` would have been installed unchecked. A missing expected package now aborts the install.
- `uninstall.sh` canonicalizes `INTEL_NPU_TOOLS_HOME` before its `rm -rf` and refuses anything that does not resolve to a subdirectory of the user's home, so neither `..` nor a symlinked path component can direct the deletion outside it.

### Changed

- OpenVINO pins allow patch releases within the validated 2026.2 minor instead of one exact build.
- `index` reports `files_removed` and `files_rechunked`, and adds a `warning` field when no file was eligible.
- Databases written by 0.2.0 gain the per-file `chunker` column automatically on first open.
- CI installs the MCP SDK and import-checks every runtime module, so a broken import in the `intel-npu-mcp` entry point can no longer ship on a green build.

## 0.2.0 - 2026-08-08

- Add private semantic indexing and retrieval using Qwen3-Embedding 0.6B INT8 on Intel NPU.
- Add `intel-npu-search` with `index`, `search`, and `status` commands.
- Add three MCP tools: `semantic_index`, `semantic_search`, and `semantic_index_status`.
- Expand support documentation for Codex, Claude, Gemini CLI, AGY, Hermes, Antigravity IDE, and OpenCode.
- Add troubleshooting, customization, performance, privacy, and agent-skill documentation.
- Add an installable example local-knowledge skill.
