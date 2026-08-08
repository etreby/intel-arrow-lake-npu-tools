import subprocess
from pathlib import Path

import cv2
import numpy as np
import openvino as ov

from .paths import ocr_model


def npu_ocr(image: np.ndarray) -> tuple[str, int]:
    core = ov.Core()
    detector = core.compile_model(ocr_model("horizontal-text-detection-0001"), "NPU")
    recognizer = core.compile_model(ocr_model("text-recognition-0014"), "NPU")
    _, _, det_h, det_w = detector.input(0).shape
    resized = cv2.resize(image, (int(det_w), int(det_h)))
    tensor = np.expand_dims(resized.transpose(2, 0, 1), 0)
    try:
        output = detector.output("boxes")
    except RuntimeError:
        output = detector.output(0)
    boxes = detector([tensor])[output]
    boxes = [box for box in boxes if not np.all(box == 0) and float(box[-1]) >= 0.30]
    _, _, rec_h, rec_w = recognizer.input(0).shape
    ratio_x, ratio_y = image.shape[1] / resized.shape[1], image.shape[0] / resized.shape[0]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    alphabet = "#1234567890abcdefghijklmnopqrstuvwxyz"
    words = []
    for box in boxes:
        x1, y1 = max(0, int(box[0] * ratio_x)), max(0, int(box[1] * ratio_y))
        x2, y2 = min(image.shape[1], int(box[2] * ratio_x)), min(image.shape[0], int(box[3] * ratio_y))
        if x2 <= x1 or y2 <= y1:
            continue
        crop = cv2.resize(gray[y1:y2, x1:x2], (int(rec_w), int(rec_h))).reshape(1, 1, int(rec_h), int(rec_w))
        scores = np.squeeze(recognizer([crop])[recognizer.output(0)])
        word = "".join(alphabet[row.argmax()] for row in scores if alphabet[row.argmax()] != "#")
        if word:
            words.append((y1, x1, word))
    words.sort(key=lambda item: (item[0] // 30, item[1]))
    return " ".join(item[2] for item in words), len(boxes)


def extract_text(path: Path) -> dict:
    image = cv2.imread(str(path))
    if image is None:
        raise ValueError(f"Could not decode image: {path}")
    npu_text, regions = npu_ocr(image)
    result = subprocess.run(
        ["tesseract", str(path), "stdout", "-l", "eng+ara", "--psm", "6"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=True,
    )
    full_text = result.stdout.strip()
    return {"text": full_text or npu_text or "(No text detected)", "npu_regions": regions, "npu_text": npu_text}
