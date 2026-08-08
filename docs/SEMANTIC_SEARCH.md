# Semantic search guide

The semantic-search feature retrieves local passages by meaning using the official OpenVINO Qwen3-Embedding 0.6B INT8 model on Intel AI Boost. It does not require a vector-database server or send documents over the network.

## Quick start

```bash
intel-npu-search index ~/Projects/my-project
intel-npu-search search "Where is authentication configured?"
intel-npu-search search "How are backups restored?" --limit 10 --root ~/Documents
intel-npu-search status
```

Indexing is incremental. A second index command skips files whose modification time and size are unchanged.

## Agent usage

After restarting an MCP client, ask naturally:

```text
Use semantic_index to index ~/Projects/my-project.
Search my indexed project for how database migrations are rolled back.
Show the indexed roots and chunk count.
```

The MCP tools are `semantic_index(path)`, `semantic_search(query, limit=5, root=null)`, and `semantic_index_status()`.

Search results contain a cosine-similarity score, absolute path, starting and ending line, and passage text. Scores rank results; they are not confidence percentages.

## Supported content and safeguards

The indexer supports common text, documentation, configuration, log, web, and source-code extensions. Files larger than 2 MiB are skipped. It also skips symlinks and directories such as `.git`, virtual environments, `node_modules`, build output, Python caches, and model directories.

The SQLite database is stored at `~/.local/share/intel-arrow-lake-npu-tools/semantic-index.sqlite3`. Only index directories you intend an AI agent to search. Indexed chunks persist locally until the database or toolkit data directory is removed.

## Measured reference performance

On the original Arrow Lake NPU 3720 test machine, indexing this repository's 29 eligible files and 57 chunks took 15.2 seconds. A warm query took approximately 1.5 seconds. Model compilation took approximately 10.7 seconds before caching. Results vary with driver, storage, file sizes, and OpenVINO version.

## Customization

Defaults are defined near the top of `src/intel_npu_tools/semantic.py`:

- `TEXT_SUFFIXES`: eligible file extensions.
- `SKIP_DIRS`: excluded directory names.
- `MAX_FILE_BYTES`: per-file size limit.
- `QUERY_INSTRUCTION`: retrieval task instruction.
- `chunk_text()`: target chunk size and line overlap.

The pipeline fixes input to 512 tokens, uses last-token pooling, normalizes vectors, and explicitly selects the NPU driver compiler. These settings are conservative for NPU static-shape compatibility. Validate relevance and NPU compilation before changing them.
