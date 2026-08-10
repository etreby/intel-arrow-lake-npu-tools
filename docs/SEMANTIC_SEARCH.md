# Semantic search guide

The semantic-search feature retrieves local passages by meaning using the official OpenVINO Qwen3-Embedding 0.6B INT8 model on Intel AI Boost. It does not require a vector-database server or send documents over the network.

## Quick start

```bash
intel-npu-search index ~/Projects/my-project
intel-npu-search search "Where is authentication configured?"
intel-npu-search search "How are backups restored?" --limit 10 --root ~/Documents
intel-npu-search status
```

Indexing is incremental. A second index command skips files whose modification time and size are unchanged, and removes entries for files under that root that no longer exist on disk. Files that still exist are never removed, so indexing a directory does not disturb a subdirectory you indexed separately.

To forget content you deleted, index its path again. If the file or directory itself is gone, the command reports what it removed instead of failing, which is how you drop a deleted path from the index.

An entry is removed only when the file is missing *and* the filesystem it was indexed from is still attached. A missing name alone is not enough: an unreadable parent directory and an unmounted disk both make a file look absent while it is still there. The indexer records each file's device, and on removal compares it against the nearest directory that still exists, so re-indexing a parent while a network or removable disk is offline leaves that disk's entries alone instead of erasing them. The trade-off is that a filesystem which changes device number across remounts — NFS shares can — keeps entries for files deleted while it was away, until you index that root again once it is back.

## Agent usage

After restarting an MCP client, ask naturally:

```text
Use semantic_index to index ~/Projects/my-project.
Search my indexed project for how database migrations are rolled back.
Show the indexed roots and chunk count.
```

The MCP tools are `semantic_index(path)`, `semantic_search(query, limit=5, root=null, rerank=null)`, `semantic_index_status()`, and `context_filter(path, query, limit=8, context_lines=0)`. The last two sections of this guide cover `rerank` and `context_filter`.

Search results contain a cosine-similarity score, absolute path, starting and ending line, and passage text. Scores rank results; they are not confidence percentages.

## Supported content and safeguards

The indexer supports common text, documentation, configuration, log, web, and source-code extensions. Files larger than 2 MiB are skipped. It also skips symlinks and directories such as `.git`, virtual environments, `node_modules`, build output, and Python caches.

Excluded directory names are matched only *below* the path you index, never against its ancestors. Indexing `~/build/my-project` therefore works normally; only a `build/` directory inside it is skipped.

A directory containing model weights (`.bin`, `.gguf`, `.onnx`, `.pt`, `.pth`, `.safetensors`) is skipped whole, along with everything beneath it. Weights themselves are already excluded by extension, but the files that ship beside them are not: tokenizer vocabularies and merge tables are `.json` and `.txt`, and OpenVINO IR graphs are `.xml`. Indexing a single Whisper directory would otherwise add several megabytes of machine-generated data to every search. Keying on the weights rather than on a directory name means a source directory named `models/` is indexed like any other. The one cost is that a source directory holding a stray `.bin` — a firmware blob, say — is skipped too.

When a run finds nothing eligible, the result carries a `warning` field naming the supported suffixes and exclusions rather than silently reporting zero files.

The SQLite database is stored at `~/.local/share/intel-npu-tools/semantic-index.sqlite3`. Only index directories you intend an AI agent to search. Indexed chunks persist locally until the database or toolkit data directory is removed.

## Measured reference performance

On the Arrow Lake NPU 3720 test machine, indexing this repository's 36 eligible files and 125 chunks from an empty database took 31.7 seconds with the model already compiled. A warm query took approximately 1.5 seconds. Results vary with driver, storage, file sizes, and OpenVINO version.

Pipeline construction takes approximately 0.9 seconds in steady state, not the 10.7 seconds this document previously reported. That larger figure matches a genuinely cold compile, which happens on a machine whose Level Zero driver cache does not hold the graph; it never described what a user experiences on a second run. Enabling OpenVINO's own model cache with `INTEL_NPU_TOOLS_MODEL_CACHE=1` does not meaningfully improve on 0.9 seconds, because the driver already caches the same graphs — what it buys is never facing that cold compile again, at the price of 1.2 GB of duplicated blobs. Embedding one 1200-character chunk takes 0.247 seconds; the pipeline cannot batch, because `batch_size` above one fails to compile on this NPU.

Re-measure with `scripts/benchmark.py` rather than trusting these numbers after a driver or OpenVINO upgrade.

The earlier figure of 15.2 seconds was measured over 29 files and 57 chunks, before directories holding model weights were excluded and before chunks were capped for the 512-token limit. Roughly twice the chunks now take roughly twice as long; the per-chunk cost is unchanged.

## Customization

Defaults are defined near the top of `src/intel_npu_tools/semantic.py`:

- `TEXT_SUFFIXES`: eligible file extensions.
- `SKIP_DIRS`: excluded directory names, matched below the indexed root.
- `MAX_FILE_BYTES`: per-file size limit.
- `TARGET_CHUNK_CHARS` / `MAX_CHUNK_CHARS`: chunk sizing, described below.
- `QUERY_INSTRUCTION`: retrieval task instruction.
- `chunk_text()`: target chunk size and line overlap.
- `CHUNKER_VERSION`: bump this after changing chunking so indexed files are re-chunked.
- `RERANK_CANDIDATES`: how many passages reranking re-scores, described below.

The pipeline fixes input to 512 tokens, uses last-token pooling, normalizes vectors, and explicitly selects the NPU driver compiler. These settings are conservative for NPU static-shape compatibility. Validate relevance and NPU compilation before changing them.

## Chunk sizing and the 512-token limit

The pipeline truncates at 512 tokens, so any chunk longer than that has its tail dropped from the embedding without an error. Chunks are therefore capped at `MAX_CHUNK_CHARS` (1500) with a `TARGET_CHUNK_CHARS` (1200) goal, and a single line longer than the cap is hard-split rather than truncated. Each split piece cites the one line it came from, so result line numbers stay accurate.

Measured against the Qwen3 tokenizer over this repository, the 1200-character target produced a maximum of 483 tokens per chunk across the 125 chunks of 36 files, with a median of 281 and a 90th percentile of 354; the previous 1600-character target reached 623 tokens and overflowed. Character limits are a proxy for token counts, so unusually dense content — minified assets, base64 blobs, CJK text — can still approach the limit. Lower `TARGET_CHUNK_CHARS` for corpora like that.

Changing any chunking value requires bumping `CHUNKER_VERSION`, which is recorded per file. Indexing a root then re-embeds its files even when they are unchanged on disk, and reports how many under `files_rechunked`. A file's own passages therefore never mix chunkers.

Roots you do not index are left exactly as they are and keep working; they are re-chunked whenever you next index them. Upgrading never deletes a root you did not name.

## Optional reranking

Embedding search is a bi-encoder: the query and each passage become vectors independently, so it ranks on topical similarity and is weak at deciding which of several similar passages is the one being asked about. A cross-encoder reads the query and a passage together and scores the pair, which is much better at that particular judgement and much slower. Reranking retrieves `RERANK_CANDIDATES` (20) passages by cosine similarity and re-scores only those, so the cost stays near one second regardless of `limit`.

The model is a separate download:

```bash
scripts/download-models.py --with-reranker
```

It is roughly 300 MB and is deliberately excluded from the default install. Reranking is then requested per query, never automatic:

```bash
intel-npu-search search "Where is authentication configured?" --rerank
```

**Reranking is off by default even when the model is installed, because measurement did not justify making it automatic.** Against this repository it helped when the model was confident and hurt when it was not. Asked how to write a skill for an agent, it promoted the correct passage with a score of +4.95. Asked why the driver requires a specific PCI id, every score fell around -6.5 and it discarded the correct passage that plain cosine similarity had ranked first. A large positive score appears to mean the model recognised the answer; when nothing scores positively, its ordering is noise and cosine similarity is the better judge. Use `--rerank` when a plain search returns several passages that look equally plausible, and leave it off otherwise.

Reranked results carry an extra `rerank_score`. It is an unbounded logit, not a cosine similarity and not a probability, so it must never be compared against `score` — and a reranked result list is no longer sorted by `score`. Requesting `--rerank` without the model installed raises an error naming the download flag rather than quietly returning unranked results.

## Filtering a single large file

`context_filter` answers a different question from search. Search finds passages across an index that was built ahead of time; `context_filter` takes one file that was never indexed, ranks its chunks against a question, and returns the best spans. It exists to keep a large build log or test transcript out of an AI agent's context window.

Everything it returns is copied verbatim from the file with the line numbers it came from, so an agent can quote and cite it. Nothing is generated, which is the reason a local language model is a poor substitute: a summary cannot be cited, and the guarantee is worth more here than the compression.

On a 100 KB build log of 2,547 lines it returned four spans, an estimated reduction from roughly 25,000 tokens to 1,200, and located a linker failure at line 1,400. The first call took 22.5 seconds; repeat questions about the same file reuse its vectors and take about a quarter of a second.

The reply reports how many chunks were dropped, and how the best dropped score compared with the weakest span kept. That gap is the honest signal about coverage: when it is small, the ranking barely distinguished what it returned from what it discarded, and the query should be narrowed or `limit` raised. Files smaller than 4 KB are refused because reading them outright costs fewer tokens than describing them, and files larger than 256 KB are refused because embedding them takes long enough to exceed the tool timeout of several MCP clients. Narrow those with `grep` first. This is not a replacement for `grep`: when the exact string is known, `grep` is faster, free, and exact.
