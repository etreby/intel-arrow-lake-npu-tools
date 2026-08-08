#!/usr/bin/env python3
"""Download redistributable model files from their upstream hosts."""

import os
import urllib.request
from pathlib import Path

from huggingface_hub import snapshot_download


data = Path(os.environ.get("INTEL_NPU_TOOLS_HOME", Path.home() / ".local/share/intel-arrow-lake-npu-tools")).expanduser()
models = data / "models"
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
