import importlib
from pathlib import Path

import pytest

from intel_npu_tools import paths


def test_default_data_directory_is_in_user_home():
    assert paths.DATA_DIR.is_absolute()
    assert str(paths.DATA_DIR).startswith(str(Path.home()))


def test_ocr_model_path():
    result = paths.ocr_model("example")
    assert result.name == "example.xml"
    assert result.parts[-3:] == ("example", "FP16", "example.xml")


def test_whisper_model_defaults_to_base(monkeypatch):
    monkeypatch.delenv("INTEL_NPU_TOOLS_WHISPER_MODEL", raising=False)
    module = importlib.reload(paths)
    assert module.WHISPER_MODEL.name == "whisper-base-int8-ov"


def test_whisper_model_is_selectable(monkeypatch):
    monkeypatch.setenv("INTEL_NPU_TOOLS_WHISPER_MODEL", "whisper-small-int8-ov")
    module = importlib.reload(paths)
    assert module.WHISPER_MODEL.name == "whisper-small-int8-ov"
    assert module.WHISPER_MODEL.parent == module.MODEL_DIR


@pytest.mark.parametrize("value", ["../../etc", "/etc/passwd", "..", ".", "  ", "a/b/.."])
def test_whisper_selection_cannot_escape_the_model_directory(monkeypatch, value):
    """The value names a directory, so a path must not turn it into a location.

    Path.name alone does not do this: it leaves ".." untouched, which would
    resolve to the parent of the models directory.
    """
    monkeypatch.setenv("INTEL_NPU_TOOLS_WHISPER_MODEL", value)
    module = importlib.reload(paths)
    assert module.WHISPER_MODEL.parent == module.MODEL_DIR
    assert module.WHISPER_MODEL.name not in ("", ".", "..")
    assert ".." not in module.WHISPER_MODEL.parts
    assert module.WHISPER_MODEL.resolve().parent == module.MODEL_DIR.resolve()


def test_reloading_paths_restores_the_default(monkeypatch):
    monkeypatch.delenv("INTEL_NPU_TOOLS_WHISPER_MODEL", raising=False)
    importlib.reload(paths)
