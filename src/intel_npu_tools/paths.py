import os
from pathlib import Path


DATA_DIR = Path(os.environ.get("INTEL_NPU_TOOLS_HOME", Path.home() / ".local/share/intel-arrow-lake-npu-tools")).expanduser()
MODEL_DIR = DATA_DIR / "models"
DEFAULT_WHISPER_MODEL = "whisper-base-int8-ov"


def _model_directory_name(value: str, fallback: str) -> str:
    """Reduce a user-supplied value to a single directory name under MODEL_DIR.

    Path.name is not sufficient on its own: it maps "a/b" to "b" as expected but
    leaves ".." untouched, which would resolve to the models directory's parent.
    Anything that is not a plain name falls back rather than raising, because
    this runs at import time and a bad environment variable should not stop
    `intel-npu-info` from reporting what is wrong.
    """
    name = Path(value.strip()).name
    if not name or name in (".", "..") or os.sep in name:
        return fallback
    return name


# Selectable, because the larger model is a genuine trade rather than an
# upgrade: measured on noisy speech it transcribed 8/8 clips correctly at 10 dB
# signal-to-noise where base managed 6/8, but it is 2.6 times slower per clip
# and three times the download. Base stays the default for dictation in a quiet
# room.
WHISPER_MODEL = MODEL_DIR / _model_directory_name(
    os.environ.get("INTEL_NPU_TOOLS_WHISPER_MODEL", ""), DEFAULT_WHISPER_MODEL
)
EMBEDDING_MODEL = MODEL_DIR / "Qwen3-Embedding-0.6B-int8-ov"
RERANK_MODEL = MODEL_DIR / "bge-reranker-base-int8-ov"
OCR_MODEL_DIR = MODEL_DIR / "ocr"
HISTORY_FILE = DATA_DIR / "speech-history.txt"
SEMANTIC_DB = DATA_DIR / "semantic-index.sqlite3"
# Compiled-model blobs, kept under DATA_DIR so that uninstall.sh removes them
# with everything else and INTEL_NPU_TOOLS_HOME relocates them.
MODEL_CACHE_DIR = DATA_DIR / "model-cache"


def ocr_model(name: str) -> Path:
    return OCR_MODEL_DIR / name / "FP16" / f"{name}.xml"
