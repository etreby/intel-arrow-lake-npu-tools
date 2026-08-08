from pathlib import Path

from intel_npu_tools import paths


def test_default_data_directory_is_in_user_home():
    assert paths.DATA_DIR.is_absolute()
    assert str(paths.DATA_DIR).startswith(str(Path.home()))


def test_ocr_model_path():
    result = paths.ocr_model("example")
    assert result.name == "example.xml"
    assert result.parts[-3:] == ("example", "FP16", "example.xml")
