"""Cover the structured screenshot reader.

The parsing is driven from a fixture copied out of real `tesseract ... tsv`
output, so these run without Tesseract, without an image, and without an NPU.
"""

import json

import pytest

from intel_npu_tools import ocr


HEADER = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext"


def row(level, block, par, line, word, left, top, width, height, conf, text=""):
    return "\t".join(
        str(part)
        for part in (level, 1, block, par, line, word, left, top, width, height, conf, text)
    )


# Two blocks: a menu bar, then a dialog whose second line is low confidence.
TSV = "\n".join([
    HEADER,
    row(1, 0, 0, 0, 0, 0, 0, 760, 300, -1),
    row(2, 1, 0, 0, 0, 13, 15, 368, 190, -1),
    row(5, 1, 1, 1, 1, 13, 15, 26, 13, 96.7, "File"),
    row(5, 1, 1, 1, 2, 49, 15, 30, 13, 96.9, "Edit"),
    row(5, 1, 1, 1, 3, 87, 15, 39, 13, 95.5, "View"),
    row(5, 1, 1, 2, 1, 21, 92, 57, 18, 95.6, "Save"),
    row(5, 1, 1, 2, 2, 85, 92, 51, 18, 95.4, "As..."),
    row(5, 2, 1, 1, 1, 20, 200, 40, 14, 45.0, "blurry"),
    row(5, 2, 1, 1, 2, 70, 200, 30, 14, 55.0, "text"),
])


@pytest.fixture
def tsv(monkeypatch):
    monkeypatch.setattr(ocr, "tesseract_tsv", lambda path: TSV)


def test_words_are_grouped_into_lines(tsv, tmp_path):
    """Tesseract's own block/paragraph/line numbers give the reading order."""
    result = ocr.structured_text(tmp_path / "shot.png")
    assert [line["text"] for line in result["lines"]] == ["File Edit View", "Save As...", "blurry text"]


def test_line_boxes_span_their_words(tsv, tmp_path):
    result = ocr.structured_text(tmp_path / "shot.png")
    assert result["lines"][0]["bbox"] == [13, 15, 126, 28]


def test_image_size_comes_from_the_page_row(tsv, tmp_path):
    result = ocr.structured_text(tmp_path / "shot.png")
    assert result["image"] == {"width": 760, "height": 300}


def test_low_confidence_words_are_dropped(tsv, tmp_path):
    """A misread word quoted with confidence is worse than one omitted."""
    result = ocr.structured_text(tmp_path / "shot.png", min_confidence=50)
    assert "blurry" not in json.dumps(result)
    assert "text" in [word for line in result["lines"] for word in line["text"].split()]


def test_low_confidence_lines_are_flagged(tsv, tmp_path):
    result = ocr.structured_text(tmp_path / "shot.png")
    assert any("scored below 60" in warning for warning in result["warnings"])


def test_text_detail_is_the_cheapest(tsv, tmp_path):
    plain = ocr.structured_text(tmp_path / "shot.png", detail="text")
    lines = ocr.structured_text(tmp_path / "shot.png", detail="lines")
    words = ocr.structured_text(tmp_path / "shot.png", detail="words")
    assert "lines" not in plain and plain["text"].startswith("File Edit View")
    assert plain["stats"]["estimated_tokens"] < lines["stats"]["estimated_tokens"]
    assert lines["stats"]["estimated_tokens"] < words["stats"]["estimated_tokens"]


def test_words_detail_carries_per_word_boxes(tsv, tmp_path):
    result = ocr.structured_text(tmp_path / "shot.png", detail="words")
    first = result["lines"][0]["words"][0]
    assert first["text"] == "File" and first["bbox"] == [13, 15, 39, 28]


def test_every_reply_states_that_this_is_not_a_widget_tree(tsv, tmp_path):
    """The tool is useless and misleading if callers think it reports UI state."""
    result = ocr.structured_text(tmp_path / "shot.png")
    assert any("not a user-interface tree" in warning for warning in result["warnings"])


def test_unknown_detail_is_refused(tsv, tmp_path):
    with pytest.raises(ValueError, match="detail must be"):
        ocr.structured_text(tmp_path / "shot.png", detail="everything")


def test_missing_tesseract_is_an_explicit_error(monkeypatch, tmp_path):
    """Tesseract supplies this tool's text, so its absence cannot be silent."""
    monkeypatch.setattr(ocr, "tesseract_tsv", lambda path: "")
    with pytest.raises(RuntimeError, match="tesseract-ocr"):
        ocr.structured_text(tmp_path / "shot.png")


def test_garbled_tsv_does_not_crash(monkeypatch, tmp_path):
    monkeypatch.setattr(ocr, "tesseract_tsv", lambda path: "not\ta\tvalid\theader\n1\t2")
    result = ocr.structured_text(tmp_path / "shot.png")
    assert result["lines"] == []
    assert any("min_confidence" in warning for warning in result["warnings"])


def test_confidence_threshold_is_clamped(tsv, tmp_path):
    assert ocr.structured_text(tmp_path / "shot.png", min_confidence=-5)["lines"]
    assert ocr.structured_text(tmp_path / "shot.png", min_confidence=500)["lines"] == []


def test_dense_word_output_warns_when_it_costs_more_than_the_image(monkeypatch, tmp_path):
    """The tool exists to save tokens; a mode that spends them must say so."""
    dense = [HEADER, row(1, 0, 0, 0, 0, 0, 0, 200, 120, -1)]
    for number in range(160):
        dense.append(row(5, 1, 1, number // 8 + 1, number % 8 + 1, 5, 5, 20, 10, 90.0, f"word{number}"))
    monkeypatch.setattr(ocr, "tesseract_tsv", lambda path: "\n".join(dense))
    result = ocr.structured_text(tmp_path / "shot.png", detail="words")
    assert result["stats"]["estimated_tokens"] > result["stats"]["estimated_image_tokens_avoided"]
    assert any("larger than the screenshot" in warning for warning in result["warnings"])


MULTIPAGE_TSV = "\n".join([
    HEADER,
    row(1, 0, 0, 0, 0, 0, 0, 700, 220, -1),
    row(5, 1, 1, 1, 1, 20, 40, 90, 12, 95.0, "PAGE"),
    row(5, 1, 1, 1, 2, 115, 40, 60, 12, 95.0, "ONE"),
    # Tesseract restarts block, paragraph, and line numbering on the next page,
    # so these rows collide with the ones above on every field except page_num.
    "\t".join(str(p) for p in (1, 2, 0, 0, 0, 0, 0, 0, 700, 220, -1, "")),
    "\t".join(str(p) for p in (5, 2, 1, 1, 1, 1, 20, 40, 90, 12, 95.0, "PAGE")),
    "\t".join(str(p) for p in (5, 2, 1, 1, 1, 2, 115, 40, 60, 12, 95.0, "TWO")),
])


def test_pages_are_not_merged_into_one_line(monkeypatch, tmp_path):
    """Without page_num in the key, page two's first line joined page one's.

    A multi-page TIFF is an accepted input, so this produced a line reading
    "PAGE ONE PAGE TWO" with a bounding box spanning two pages.
    """
    monkeypatch.setattr(ocr, "tesseract_tsv", lambda path: MULTIPAGE_TSV)
    result = ocr.structured_text(tmp_path / "scan.tif")
    assert [line["text"] for line in result["lines"]] == ["PAGE ONE", "PAGE TWO"]
    assert [line["page"] for line in result["lines"]] == [1, 2]
    assert result["stats"]["pages"] == 2


def test_multi_page_replies_warn_that_boxes_are_page_local(monkeypatch, tmp_path):
    monkeypatch.setattr(ocr, "tesseract_tsv", lambda path: MULTIPAGE_TSV)
    result = ocr.structured_text(tmp_path / "scan.tif")
    assert any("2 pages" in warning for warning in result["warnings"])


def test_single_page_replies_omit_the_page_field(tsv, tmp_path):
    """It is noise on the overwhelmingly common single-screenshot case."""
    result = ocr.structured_text(tmp_path / "shot.png")
    assert all("page" not in line for line in result["lines"])
    assert result["stats"]["pages"] == 1
