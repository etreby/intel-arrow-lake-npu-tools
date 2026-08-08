import os
from pathlib import Path


DATA_DIR = Path(os.environ.get("INTEL_NPU_TOOLS_HOME", Path.home() / ".local/share/intel-arrow-lake-npu-tools")).expanduser()
MODEL_DIR = DATA_DIR / "models"
WHISPER_MODEL = MODEL_DIR / "whisper-base-int8-ov"
EMBEDDING_MODEL = MODEL_DIR / "Qwen3-Embedding-0.6B-int8-ov"
OCR_MODEL_DIR = MODEL_DIR / "ocr"
HISTORY_FILE = DATA_DIR / "speech-history.txt"
SEMANTIC_DB = DATA_DIR / "semantic-index.sqlite3"


def ocr_model(name: str) -> Path:
    return OCR_MODEL_DIR / name / "FP16" / f"{name}.xml"
