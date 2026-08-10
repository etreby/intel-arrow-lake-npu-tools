#!/usr/bin/env python3
"""Download redistributable model files from their upstream hosts."""

import argparse
import urllib.request

from huggingface_hub import snapshot_download

# The data directory is resolved by the package rather than recomputed here, so
# that this script cannot disagree with the programs about where the models
# live. It matters more than it looks: an installation predating the rename
# keeps everything under the old directory name, and the resolver picks the old
# one only while the new one does not exist. Creating the new directory here
# would therefore not just download to the wrong place — it would make the
# existing models, settings and semantic index appear to have vanished.
#
# Both callers (install.sh and intel-npu-tools-setup) pip-install the package
# into the virtual environment before running this, and config imports nothing
# beyond the standard library, so the import is both safe and cheap.
from intel_npu_tools.config import DATA_DIR


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument(
    "--with-reranker",
    action="store_true",
    help="Also download the optional BGE reranker (~300 MB) used to re-score search results",
)
parser.add_argument(
    "--with-whisper-small",
    action="store_true",
    help="Also download Whisper Small INT8 (~250 MB), more accurate in noise but slower than base",
)
arguments = parser.parse_args()

models = DATA_DIR / "models"
models.mkdir(parents=True, exist_ok=True)

print("Downloading OpenVINO Whisper Base INT8…")
snapshot_download(
    repo_id="OpenVINO/whisper-base-int8-ov",
    local_dir=models / "whisper-base-int8-ov",
)

print("Downloading OpenVINO Qwen3 Embedding 0.6B INT8…")
snapshot_download(
    repo_id="OpenVINO/Qwen3-Embedding-0.6B-int8-ov",
    local_dir=models / "Qwen3-Embedding-0.6B-int8-ov",
)

if arguments.with_whisper_small:
    print("Downloading OpenVINO Whisper Small INT8…")
    snapshot_download(
        repo_id="OpenVINO/whisper-small-int8-ov",
        local_dir=models / "whisper-small-int8-ov",
    )

# Optional, and left out of the default install so the mandatory download does
# not grow by a third for a feature most users will not turn on.
if arguments.with_reranker:
    print("Downloading OpenVINO BGE Reranker Base INT8…")
    snapshot_download(
        repo_id="OpenVINO/bge-reranker-base-int8-ov",
        local_dir=models / "bge-reranker-base-int8-ov",
    )

base = "https://storage.openvinotoolkit.org/repositories/open_model_zoo/2023.0/models_bin/1"
for name in ("horizontal-text-detection-0001", "text-recognition-0014"):
    destination = models / "ocr" / name / "FP16"
    destination.mkdir(parents=True, exist_ok=True)
    for extension in ("xml", "bin"):
        target = destination / f"{name}.{extension}"
        if target.exists() and target.stat().st_size:
            continue
        url = f"{base}/{name}/FP16/{name}.{extension}"
        print(f"Downloading {url}")
        urllib.request.urlretrieve(url, target)

print(f"Models installed in {models}")
