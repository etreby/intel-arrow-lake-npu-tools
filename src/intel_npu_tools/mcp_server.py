import subprocess
import tempfile
from pathlib import Path

import openvino as ov
from mcp.server import MCPServer

from .audio import transcribe_file
from .ocr import extract_text
from .paths import WHISPER_MODEL
from .semantic import SemanticIndex


mcp = MCPServer(
    "intel-arrow-lake-npu-tools",
    title="Intel Arrow Lake NPU Tools",
    description="Private local speech, OCR, and semantic search using Intel AI Boost.",
)

semantic = SemanticIndex()


def local_file(value: str, suffixes: tuple[str, ...]) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"File does not exist: {path}")
    if path.suffix.lower() not in suffixes:
        raise ValueError(f"Unsupported file type: {path.suffix}")
    return path


@mcp.tool()
def npu_status() -> dict:
    """Report OpenVINO devices and whether Intel AI Boost is available."""
    core = ov.Core()
    devices = {device: core.get_property(device, "FULL_DEVICE_NAME") for device in core.available_devices}
    return {"npu_available": "NPU" in devices, "devices": devices, "whisper_model": str(WHISPER_MODEL)}


@mcp.tool()
def transcribe_audio(audio_path: str) -> str:
    """Transcribe a local audio file on the Intel NPU."""
    path = local_file(audio_path, (".wav", ".mp3", ".m4a", ".flac", ".ogg", ".webm", ".opus"))
    return transcribe_file(path)


@mcp.tool()
def record_and_transcribe(seconds: int = 10) -> str:
    """Record the default microphone for 1-60 seconds and transcribe on the NPU."""
    seconds = max(1, min(int(seconds), 60))
    with tempfile.NamedTemporaryFile(suffix=".wav") as audio:
        subprocess.run(["pw-record", "--rate", "16000", "--channels", "1", "--format", "s16", "--sample-count", str(16000 * seconds), audio.name], check=True, timeout=seconds + 10)
        return transcribe_file(Path(audio.name))


@mcp.tool()
def ocr_image(image_path: str) -> dict:
    """Extract English and Arabic text from a local image using NPU text models."""
    return extract_text(local_file(image_path, (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff")))


@mcp.tool()
def ocr_current_monitor() -> dict:
    """Capture the current monitor and extract its text."""
    with tempfile.NamedTemporaryFile(suffix=".png") as image:
        subprocess.run(["spectacle", "--current", "--background", "--nonotify", "--output", image.name], check=True, timeout=30)
        return extract_text(Path(image.name))


@mcp.tool()
def semantic_index(path: str) -> dict:
    """Index a local text file or directory for private semantic search on the Intel NPU."""
    return semantic.index(path)


@mcp.tool()
def semantic_search(query: str, limit: int = 5, root: str | None = None) -> list[dict]:
    """Search indexed local files by meaning using Intel NPU embeddings."""
    return semantic.search(query, limit, root)


@mcp.tool()
def semantic_index_status() -> dict:
    """Report the local semantic index database, roots, file count, and chunk count."""
    return semantic.status()


@mcp.tool()
def open_speech_app() -> str:
    """Open the interactive speech-to-text desktop application."""
    subprocess.Popen(["intel-npu-speech"], start_new_session=True)
    return "Opened Intel NPU Speech to Text."


@mcp.tool()
def open_ocr_selector() -> str:
    """Open the rectangular screenshot OCR selector."""
    subprocess.Popen(["intel-npu-ocr"], start_new_session=True)
    return "Opened Intel NPU Screenshot OCR."


def main():
    mcp.run(transport="stdio")
