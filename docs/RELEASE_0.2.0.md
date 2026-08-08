# Intel Arrow Lake NPU Tools 0.2.0

This release turns Intel AI Boost on Arrow Lake Linux systems into a private local retrieval engine for AI agents, while preserving the existing speech and OCR workflows.

## Highlights

- Semantic indexing and meaning-based search run on the Intel NPU with Qwen3-Embedding 0.6B INT8.
- A local SQLite index avoids external vector databases and network services.
- Ten MCP tools are available to Codex, Claude, Gemini CLI, AGY, Hermes, Antigravity IDE, OpenCode, and compatible clients.
- The `intel-npu-search` CLI supports incremental indexing, ranked search, root filters, and status inspection.
- A validated example agent skill demonstrates safe, source-cited local retrieval.
- New guides cover setup, usage, privacy, debugging, customization, and skill development.

## Quick start

```bash
git clone https://github.com/etreby/intel-arrow-lake-npu-tools.git
cd intel-arrow-lake-npu-tools
./install.sh --with-driver
```

Log out and back in after the first driver installation, then:

```bash
intel-npu-search index ~/Projects/my-project
intel-npu-search search "Where is authentication configured?"
```

The project is unofficial and community maintained. Confirm supported hardware and read the driver safety notes before installation.

## Verified reference system

The release was validated on an Intel Arrow Lake NPU 3720 (`8086:ad1d`) running Pop!_OS/Ubuntu 24.04-compatible userspace and OpenVINO 2026.2.1. Real NPU tests covered model compilation, document/query embeddings, incremental indexing, ranked retrieval, and discovery/calling through a real MCP client.

See the README and `docs/` directory for full details.
