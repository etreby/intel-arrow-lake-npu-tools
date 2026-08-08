# Intel Arrow Lake NPU Tools for Linux

An unofficial, community-maintained toolkit that makes the integrated **Intel AI Boost NPU** in Arrow Lake processors useful on Linux. It provides private local speech transcription, screenshot OCR, hardware verification, and MCP tools that AI agents can call.

> This project is not affiliated with, sponsored by, or endorsed by Intel Corporation. Intel, Intel Core, OpenVINO, and Intel AI Boost are trademarks of their respective owners.

## Why this exists

Linux can expose an Arrow Lake NPU as `/dev/accel/accel0`, but applications still need Intel's Level Zero NPU user-mode driver, OpenVINO, compatible models, permissions, and integration code. This repository assembles those pieces into useful desktop and agent workflows.

The NPU is a good fit for efficient background inference. It does **not** replace a discrete GPU for model training, large language models, or image generation.

## Features

- **Speech to text:** multilingual Whisper Base INT8 runs locally on the NPU.
- **Screenshot OCR:** select a region and copy recognized English or Arabic text.
- **MCP server:** Codex, Claude, Gemini CLI, AGY/Antigravity CLI, Hermes, Antigravity IDE, OpenCode, and other MCP clients can transcribe audio, record the microphone, OCR images, or read the current monitor.
- **Hardware diagnostics:** report every OpenVINO device and confirm `Intel(R) AI Boost` is available.
- **Reversible installation:** user applications and models are isolated under `~/.local`; the uninstaller deliberately preserves system drivers.

## Supported hardware and software

The initial tested target is:

- Intel Arrow Lake integrated NPU 3720, PCI ID `8086:ad1d`
- Intel Core Ultra 200-series desktop processors, including Core Ultra 9 285K
- Ubuntu 24.04 or an Ubuntu 24.04-compatible distribution
- Linux kernel 6.8 or newer with `intel_vpu`
- KDE Plasma Wayland for the included screenshot workflow

OpenVINO officially identifies Arrow Lake's NPU 3720 by PCI ID `0xAD1D`. Other Intel NPU generations may work with code changes, but the bundled driver safety check intentionally refuses unknown PCI IDs.

## Quick installation

```bash
git clone https://github.com/etreby/intel-arrow-lake-npu-tools.git
cd intel-arrow-lake-npu-tools
./install.sh --with-driver
```

`--with-driver` installs Intel's signed Ubuntu 24.04 NPU user-mode packages and firmware, adds the current user to `render`, creates an isolated Python environment, downloads the models from their official upstream locations, and installs the desktop and MCP tools.

Log out and back in after the first driver installation, then verify:

```bash
intel-npu-info
```

Expected output includes:

```json
"NPU": "Intel(R) AI Boost"
```

If the driver is already installed, omit `--with-driver`:

```bash
./install.sh
```

To skip automatic MCP client registration:

```bash
./install.sh --without-mcp
```

## Desktop usage

Launch these applications from the desktop menu:

- **Intel NPU Speech to Text:** click Start, speak, then Stop and transcribe. The result is copied to the clipboard.
- **Intel NPU Screenshot OCR:** select a rectangular region. Recognized text is displayed and copied.

KDE shortcut declarations:

- `Meta+Alt+S` — Speech to Text
- `Meta+Alt+O` — Screenshot OCR

`Meta` is normally the Windows-logo key. Desktop environments may require one new login before discovering newly installed shortcuts.

## AI agent and MCP usage

The local stdio MCP command is:

```bash
intel-npu-mcp
```

It exposes:

| Tool | Purpose |
| --- | --- |
| `npu_status` | Verify OpenVINO and list available devices |
| `transcribe_audio` | Transcribe a local audio file on the NPU |
| `record_and_transcribe` | Record the default microphone for a bounded duration |
| `ocr_image` | Extract English/Arabic text from an image |
| `ocr_current_monitor` | Capture and OCR the current monitor |
| `open_speech_app` | Open the interactive speech application |
| `open_ocr_selector` | Open interactive region OCR |

Example agent requests:

```text
Use intel-npu-tools to transcribe ~/recording.m4a.
Use the NPU to OCR ~/Pictures/error.png.
Record my microphone for 15 seconds and transcribe it.
Read the text currently visible on my monitor.
```

Manual Codex registration:

```bash
codex mcp add intel-npu-tools -- "$HOME/.local/bin/intel-npu-mcp"
```

Manual Claude Code registration:

```bash
claude mcp add --scope user intel-npu-tools -- "$HOME/.local/bin/intel-npu-mcp"
```

Manual Hermes registration:

```bash
hermes mcp add intel-npu-tools --command "$HOME/.local/bin/intel-npu-mcp"
```

Manual Gemini CLI registration:

```bash
gemini mcp add --scope user intel-npu-tools "$HOME/.local/bin/intel-npu-mcp"
```

AGY/Antigravity CLI reads global servers from `~/.gemini/config/mcp_config.json`:

```json
{
  "mcpServers": {
    "intel-npu-tools": {
      "command": "/home/YOUR_USER/.local/bin/intel-npu-mcp",
      "args": []
    }
  }
}
```

OpenCode reads global configuration from `~/.config/opencode/opencode.json`:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "intel-npu-tools": {
      "type": "local",
      "command": ["/home/YOUR_USER/.local/bin/intel-npu-mcp"],
      "enabled": true,
      "timeout": 60000
    }
  }
}
```

Any MCP client can use this stdio configuration:

```json
{
  "mcpServers": {
    "intel-npu-tools": {
      "command": "/home/YOUR_USER/.local/bin/intel-npu-mcp",
      "args": []
    }
  }
}
```

## How the NPU is utilized

```text
Microphone/audio ──> Whisper Base INT8 ──> OpenVINO GenAI ──> Intel NPU
Screenshot/image ──> text detector + recognizer ──> OpenVINO ──> Intel NPU
                                      └──> Tesseract layout/language fallback
AI agent ──> local stdio MCP server ──> the same NPU pipelines
```

All inference targets `NPU` explicitly. The included tools do not silently redirect workloads to a discrete GPU. This allows an NVIDIA or Intel GPU to remain available for gaming, rendering, Ollama, or larger AI workloads.

## Privacy

- No network server is started.
- MCP communication uses a local child process over stdin/stdout.
- Audio and screenshots are processed locally.
- Network access is needed only during installation to download software and models.
- Temporary recordings and screenshots are deleted after processing.

## Troubleshooting

### `/dev/accel/accel0` is missing

```bash
lspci -nn | grep -i ad1d
lsmod | grep intel_vpu
journalctl -k -b | grep -i intel_vpu
```

Update the kernel/firmware for your distribution before replacing unrelated graphics drivers.

### NPU exists but OpenVINO shows only CPU/GPU

```bash
groups
ls -l /dev/accel/accel0
```

The user must belong to `render`. Log out and back in after group changes.

### Speech produces no text

Check the default PipeWire microphone:

```bash
pactl get-default-source
pw-record --rate 16000 --channels 1 /tmp/microphone-test.wav
```

### OCR limitations

Intel's compact recognition model focuses on lowercase Latin letters and digits. Tesseract supplements it for punctuation, layout, English, and Arabic. Stylized fonts and very small text may remain imperfect.

## Development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
python -m compileall -q src
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for contribution guidelines and proposed areas of work.

## Uninstall

```bash
./uninstall.sh
```

The uninstaller removes user applications, models, and MCP registrations. It intentionally preserves system-level NPU firmware and drivers.

## Upstream components and documentation

- [Intel Linux NPU Driver](https://github.com/intel/linux-npu-driver)
- [OpenVINO NPU plugin](https://github.com/openvinotoolkit/openvino/tree/master/src/plugins/intel_npu)
- [OpenVINO GenAI on NPU](https://docs.openvino.ai/2026/openvino-workflow-generative/inference-with-genai/inference-with-genai-on-npu.html)
- [Official MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- [OpenVINO Whisper Base INT8](https://huggingface.co/OpenVINO/whisper-base-int8-ov)
- [Open Model Zoo OCR tutorial](https://docs.openvino.ai/2024/notebooks/optical-character-recognition-with-output.html)

## License

Project code is released under the [MIT License](LICENSE). Downloaded drivers, models, runtimes, and trademarks remain under their respective upstream licenses. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
