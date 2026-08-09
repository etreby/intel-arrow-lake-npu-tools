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

## Reranker model is missing

`--rerank` and `semantic_search(rerank=true)` raise a `FileNotFoundError` when the optional model is absent, rather than quietly returning unranked results. Install it with `scripts/download-models.py --with-reranker` inside the installed virtual environment. The expected directory is `models/bge-reranker-base-int8-ov` and requires roughly 300 MB. Plain search keeps working without it, and reranking is off by default in any case.

## Reranking makes results worse

Expected on some queries, and the reason it is opt-in. The cross-encoder is reliable when it is confident and unreliable when it is not: a strongly positive `rerank_score` means it recognised the answer, while a set of results whose scores are all negative means it recognised nothing and ordered them arbitrarily, discarding a cosine ranking that was better. Drop `--rerank` for those queries. Do not work around it by moving the reranker to the CPU; that changes nothing about relevance and gives up the resource isolation described below.

## A keyboard shortcut does nothing

`Meta+F9` and `Meta+Alt+O` are registered by `install.sh` into KDE's `kglobalshortcutsrc`, and KDE's shortcut daemon reads that file only when a session starts. Log out and back in after installing. Check that the binding exists:

```bash
kreadconfig5 --file kglobalshortcutsrc --group intel-npu-speech.desktop --key _launch
```

**A binding whose first field is empty** — `_launch=,Meta+F9,Intel NPU Speech to Text` — means KDE found another component already holding that key and discarded ours at login. Find the owner and pick a different key:

```bash
grep -n "Meta+F9" ~/.config/kglobalshortcutsrc
```

This is why speech moved off `Meta+Alt+S`: KDE's accessibility component binds it to "Toggle Screen Reader On and Off" by default. The installer now refuses to write a key that is already taken rather than registering one that will be discarded.

An empty result means it was never registered, which is what happens when the KDE configuration tools are absent or the desktop is not KDE. Bind the application yourself in System Settings, or start it from the desktop menu.

Installations made before this was fixed have no binding at all, because the `X-KDE-Shortcuts` line in the desktop file does not register anything for a desktop file in `~/.local/share/applications`. Re-run `install.sh` to add it.

If the binding is present and the key still does nothing, something is intercepting it before KDE. Keyboard remappers that read input at the device level — Toshy, xremap, keyd, kanata, input-remapper — all do this on Wayland. Stop the remapper briefly and re-test to identify it:

```bash
systemctl --user stop toshy-config.service    # example; start it again afterwards
```

## Transcription is wrong in a noisy room

Install the larger speech model and select it:

```bash
scripts/download-models.py --with-whisper-small
export INTEL_NPU_TOOLS_WHISPER_MODEL=whisper-small-int8-ov
```

Measured over recorded clips mixed with noise, Whisper Small transcribed 8 of 8 correctly at 10 dB signal-to-noise where Base managed 6, and 6 against 5 at 5 dB. Neither helps once the noise overwhelms the speech: both scored 2 of 8 at 0 dB, so fix the microphone rather than the model in that case. Small costs roughly 2.6 times the transcription time, which is why Base remains the default. Unset the variable to go back.

The value names a directory inside the models directory; anything that is not a plain directory name falls back to the default rather than failing, so a typo shows up as unchanged behaviour rather than an error.

## Screen text is misread or missing

`screen_to_text` transcribes with Tesseract, which is weakest on exactly the small antialiased text most interfaces use: on a synthetic editor window it read `src` as `sre` and `mcp_server.py` as `mep_server.py`. Check the per-line `conf` value before acting on a line, since it drops noticeably on the lines that are wrong, and lower `min_confidence` if whole lines are missing rather than wrong. There is no NPU path to switch to; the bundled recognizer is limited to lowercase Latin and digits, which is worse. If the target is a web page, read Playwright's accessibility tree instead — it is exact, it includes content scrolled out of view, and it costs no model tokens.

## Filtering a file is slower than expected

`context_filter` embeds every chunk on the first call, at roughly a quarter of a second per 1200 characters, so a 100 KB file takes about 22 seconds and the 256 KB ceiling takes close to a minute. Repeat questions about the same file reuse its vectors and return in about a quarter of a second. If a client times out, filter a smaller file: narrow it with `grep` first, which is also the faster tool whenever the exact string is known.

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

Check that files use supported extensions, are below 2 MiB, and are outside excluded directories. When nothing was eligible, `index` reports a `warning` field explaining which filters applied. Use `--root` only when that root was indexed.

## Enable deeper OpenVINO logging

```bash
OV_LOG_LEVEL=DEBUG intel-npu-search search "test query"
```

When reporting an issue, include the toolkit commit, `intel-npu-info`, distribution/kernel, installed NPU package versions, exact command, and complete error text. Remove private document contents before sharing logs or index data.
