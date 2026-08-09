import json
import subprocess
import threading
from pathlib import Path

import numpy as np

from .paths import ocr_model
from .runtime import npu_properties


DETECTOR = "horizontal-text-detection-0001"
RECOGNIZER = "text-recognition-0014"

_models = None
_lock = threading.RLock()


def ocr_models():
    """Compile both OCR models once per process.

    They were previously compiled on every npu_ocr() call, so a single
    screenshot paid the full driver compilation twice before a pixel was read.
    """
    global _models
    with _lock:
        if _models is None:
            import openvino as ov

            for name in (DETECTOR, RECOGNIZER):
                if not ocr_model(name).exists():
                    raise FileNotFoundError(
                        f"OCR model not found at {ocr_model(name)}; run scripts/download-models.py"
                    )
            core = ov.Core()
            properties = npu_properties()
            _models = (
                core.compile_model(ocr_model(DETECTOR), "NPU", properties),
                core.compile_model(ocr_model(RECOGNIZER), "NPU", properties),
            )
        return _models


def npu_ocr(image: np.ndarray) -> tuple[str, int]:
    # A CompiledModel reuses one implicit infer request, so two concurrent MCP
    # calls against the shared models would race. The NPU runs one inference at
    # a time regardless (OPTIMAL_NUMBER_OF_INFER_REQUESTS is 1), so serialising
    # here costs nothing that the device was not already serialising.
    with _lock:
        detector, recognizer = ocr_models()
        return _run_ocr(image, detector, recognizer)


def _run_ocr(image: np.ndarray, detector, recognizer) -> tuple[str, int]:
    import cv2

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
        characters = (alphabet[row.argmax()] for row in scores)
        word = "".join(character for character in characters if character != "#")
        if word:
            words.append((y1, x1, word))
    words.sort(key=lambda item: (item[0] // 30, item[1]))
    return " ".join(item[2] for item in words), len(boxes)


def tesseract_text(path: Path) -> str:
    """Read layout, punctuation, and non-Latin scripts. Returns "" when unavailable."""
    try:
        result = subprocess.run(
            ["tesseract", str(path), "stdout", "-l", "eng+ara", "--psm", "6"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=True,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip()


def capture_current_monitor(target: Path) -> Path:
    """Screenshot the focused monitor into target."""
    subprocess.run(
        ["spectacle", "--current", "--background", "--nonotify", "--output", str(target)],
        check=True,
        timeout=30,
    )
    return target


def tesseract_tsv(path: Path) -> str:
    """Word-level OCR with layout structure. Returns "" when unavailable.

    Page segmentation mode 3 rather than the 6 used by tesseract_text above.
    Mode 6 assumes one uniform block of text, which on a two-column screen
    stitches the columns together: a file name from a sidebar and a line of code
    from the editor beside it come back as one line. Mode 3 detects the columns
    and keeps them apart, which is the whole reason to read the structured
    output rather than the plain text.
    """
    try:
        result = subprocess.run(
            ["tesseract", str(path), "stdout", "-l", "eng+ara", "--psm", "3", "tsv"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=True,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout


# The same rough rule context_filter.py uses, and just as approximate. It is
# only ever used to tell the caller roughly what a reply cost them.
CHARS_PER_TOKEN = 4
# A screenshot sent to a vision model is charged by area, near enough to
# width * height / 750, and current models stop counting at about this many.
IMAGE_TOKEN_DIVISOR = 750
IMAGE_TOKEN_CAP = 4784


def _parse_tsv(tsv: str, min_confidence: int) -> tuple[list[dict], dict, int, int]:
    """Group Tesseract's word rows into lines using its own layout analysis.

    Tesseract already assigns every word a page, block, paragraph, and line, so
    reading order comes from real page segmentation rather than from sorting by
    rounded y coordinate the way npu_ocr does. That heuristic collapses on any
    layout with columns or a side panel, which describes most application
    windows.

    Returns the lines, the first page's size, the word count, and the page
    count.
    """
    rows = [line.split("\t") for line in tsv.splitlines()]
    if not rows or rows[0][:1] != ["level"]:
        return [], {}, 0, 0
    header = rows[0]
    index = {name: position for position, name in enumerate(header)}
    size: dict = {}
    grouped: dict[tuple[str, str, str, str], list[dict]] = {}
    words = 0
    pages = 0
    for row in rows[1:]:
        if len(row) != len(header):
            continue
        level = row[index["level"]]
        left, top = int(row[index["left"]]), int(row[index["top"]])
        width, height = int(row[index["width"]]), int(row[index["height"]])
        if level == "1":
            # One of these per page. Keep the first, because the reply reports a
            # single image size and the last page's would silently describe the
            # wrong one for a caller sizing a click target.
            pages += 1
            if not size:
                size = {"width": width, "height": height}
            continue
        if level != "5":
            continue
        text = row[index["text"]].strip()
        try:
            confidence = float(row[index["conf"]])
        except ValueError:
            continue
        if not text or confidence < min_confidence:
            continue
        words += 1
        # page_num belongs in the key. Tesseract restarts block, paragraph, and
        # line numbering on every page of a multi-page TIFF, so without it the
        # first line of page two joins the first line of page one into a single
        # line with a bounding box spanning both.
        key = (
            row[index["page_num"]],
            row[index["block_num"]],
            row[index["par_num"]],
            row[index["line_num"]],
        )
        grouped.setdefault(key, []).append({
            "text": text,
            "conf": confidence,
            "bbox": [left, top, left + width, top + height],
        })

    lines = []
    for key in sorted(grouped, key=lambda item: tuple(int(part) for part in item)):
        members = grouped[key]
        boxes = [member["bbox"] for member in members]
        lines.append({
            "text": " ".join(member["text"] for member in members),
            "bbox": [
                min(box[0] for box in boxes), min(box[1] for box in boxes),
                max(box[2] for box in boxes), max(box[3] for box in boxes),
            ],
            "conf": round(sum(member["conf"] for member in members) / len(members)),
            "page": int(key[0]),
            "words": members,
        })
    return lines, size, words, pages


def structured_text(path: Path, detail: str = "lines", min_confidence: int = 40) -> dict:
    """Render a screenshot as compact structured text instead of an image."""
    if detail not in ("text", "lines", "words"):
        raise ValueError(f"detail must be text, lines, or words; got {detail!r}")
    min_confidence = max(0, min(int(min_confidence), 100))

    tsv = tesseract_tsv(path)
    if not tsv:
        raise RuntimeError(
            "Tesseract produced no output. It provides this tool's text; install it with "
            "apt-get install tesseract-ocr tesseract-ocr-eng tesseract-ocr-ara."
        )
    lines, size, words, pages = _parse_tsv(tsv, min_confidence)

    reading_order = "\n".join(line["text"] for line in lines)
    payload: dict = {"lines": []}
    if detail == "text":
        payload = {"text": reading_order}
    elif detail == "lines":
        payload = {
            "lines": [
                {"text": line["text"], "bbox": line["bbox"], "conf": line["conf"],
                 **({"page": line["page"]} if pages > 1 else {})}
                for line in lines
            ]
        }
    else:
        payload = {
            "lines": [
                {
                    "text": line["text"],
                    "bbox": line["bbox"],
                    "conf": line["conf"],
                    **({"page": line["page"]} if pages > 1 else {}),
                    "words": [
                        {"text": word["text"], "bbox": word["bbox"], "conf": round(word["conf"])}
                        for word in line["words"]
                    ],
                }
                for line in lines
            ]
        }

    rendered = len(json.dumps(payload, ensure_ascii=False))
    pixels = size.get("width", 0) * size.get("height", 0)
    image_tokens = min(IMAGE_TOKEN_CAP, pixels // IMAGE_TOKEN_DIVISOR) if pixels else 0
    text_tokens = rendered // CHARS_PER_TOKEN
    low_confidence = sum(1 for line in lines if line["conf"] < 60)

    warnings = [
        "Text is OCR output, not a user-interface tree. It cannot report widget type, "
        "enabled or checked state, focus, scroll position, or anything off-screen."
    ]
    if low_confidence:
        warnings.append(f"{low_confidence} of {len(lines)} lines scored below 60 and may be misread.")
    if detail == "words" and text_tokens > image_tokens > 0:
        warnings.append(
            "This reply is larger than the screenshot would have been. Use detail='lines' "
            "or 'text' unless per-word boxes are genuinely needed."
        )
    if not lines:
        warnings.append("No text cleared the confidence threshold; try lowering min_confidence.")
    if pages > 1:
        # Bounding boxes are page-local, so a caller mapping one to a click
        # target needs to know which page it came from.
        warnings.append(
            f"This file has {pages} pages. Each line carries its page number, and every "
            "bounding box is relative to that page rather than to the file."
        )

    return {
        "source": str(path),
        "engine": "tesseract (eng+ara)",
        "detail": detail,
        "image": size,
        **payload,
        "stats": {
            "lines": len(lines),
            "words": words,
            "pages": pages,
            "estimated_tokens": text_tokens,
            "estimated_image_tokens_avoided": image_tokens,
        },
        "estimates": (
            "Token counts are approximate. Image cost is estimated as pixels divided by 750, "
            f"capped at {IMAGE_TOKEN_CAP}, which is roughly how current vision models charge."
        ),
        "warnings": warnings,
    }


def extract_text(path: Path) -> dict:
    import cv2

    image = cv2.imread(str(path))
    if image is None:
        raise ValueError(f"Could not decode image: {path}")
    npu_text, regions = npu_ocr(image)
    full_text = tesseract_text(path)
    return {"text": full_text or npu_text or "(No text detected)", "npu_regions": regions, "npu_text": npu_text}
