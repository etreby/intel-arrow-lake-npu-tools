import os
from pathlib import Path


DATA_DIR = Path(os.environ.get("INTEL_NPU_TOOLS_HOME", Path.home() / ".local/share/intel-arrow-lake-npu-tools")).expanduser()
MODEL_DIR = DATA_DIR / "models"
WHISPER_MODEL = MODEL_DIR / "whisper-base-int8-ov"
OCR_MODEL_DIR = MODEL_DIR / "ocr"
HISTORY_FILE = DATA_DIR / "speech-history.txt"


def ocr_model(name: str) -> Path:
    return OCR_MODEL_DIR / name / "FP16" / f"{name}.xml"
