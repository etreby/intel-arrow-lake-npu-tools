import subprocess
import threading
from pathlib import Path

import numpy as np

from .paths import WHISPER_MODEL
from .runtime import npu_properties


_pipeline = None
_lock = threading.RLock()


def decode_audio(path: Path) -> np.ndarray:
    result = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-f", "f32le", "-acodec", "pcm_f32le", "-ar", "16000", "-ac", "1", "-"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    audio = np.frombuffer(result.stdout, dtype=np.float32)
    if audio.size < 1600:
        raise ValueError("Audio must be at least 0.1 seconds long")
    return audio


def pipeline():
    global _pipeline
    with _lock:
        if _pipeline is None:
            import openvino_genai as ov_genai

            if not WHISPER_MODEL.exists():
                raise FileNotFoundError(f"Whisper model not found at {WHISPER_MODEL}; run scripts/download-models.py")
            _pipeline = ov_genai.WhisperPipeline(str(WHISPER_MODEL), "NPU", **npu_properties())
        return _pipeline


def transcribe(audio: np.ndarray) -> str:
    if not audio.size or float(np.max(np.abs(audio))) < 0.002:
        return "(No speech detected)"
    with _lock:
        text = str(pipeline().generate(audio)).strip()
    return text or "(No speech detected)"


def transcribe_file(path: Path) -> str:
    return transcribe(decode_audio(path))
