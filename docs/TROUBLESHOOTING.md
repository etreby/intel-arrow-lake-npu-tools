# Troubleshooting and debugging

## Collect a basic diagnostic

```bash
intel-npu-info
id
ls -l /dev/accel/accel0
journalctl -k -b --no-pager | grep -Ei 'intel_vpu|npu|vpu'
```

The device list must contain `NPU: Intel(R) AI Boost`. The active login must include the `render` group after driver installation; log out and back in if it does not.

## MCP client cannot find the tools

Run `intel-npu-mcp` directly and confirm it stays open waiting for stdio input. Then inspect the client registration documented in the README. Restart existing agent sessions because MCP tool lists are normally loaded only at session startup.

## Embedding model is missing

Re-run the repository's `scripts/download-models.py` inside the installed virtual environment. The expected directory is `models/Qwen3-Embedding-0.6B-int8-ov` and requires roughly 600 MB.

## NPU compilation fails

```bash
dpkg -l | grep -E 'intel-(driver-compiler|level-zero|fw)-npu'
sg render -c 'intel-npu-info'
```

The embedding pipeline selects `NPU_COMPILER_TYPE=DRIVER`, matching the Intel Ubuntu packages installed by this project. Do not silently change the semantic pipeline to CPU or GPU; doing so defeats the project's resource-isolation promise.

## Search returns no results

```bash
intel-npu-search status
intel-npu-search index /absolute/path/to/documents
intel-npu-search search "specific natural-language question" --limit 10
```

Check that files use supported extensions, are below 2 MiB, and are outside excluded directories. Use `--root` only when that root was indexed.

## Enable deeper OpenVINO logging

```bash
OV_LOG_LEVEL=DEBUG intel-npu-search search "test query"
```

When reporting an issue, include the toolkit commit, `intel-npu-info`, distribution/kernel, installed NPU package versions, exact command, and complete error text. Remove private document contents before sharing logs or index data.
