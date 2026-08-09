"""Cover the NPU plugin properties shared by every model this toolkit compiles.

These run without OpenVINO installed, which is the point: runtime.py must stay
importable on a machine that has no inference stack, because the continuous
integration workflow asserts exactly that.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from intel_npu_tools import runtime


SRC = Path(__file__).resolve().parent.parent / "src"


@pytest.fixture(autouse=True)
def clear_flags(monkeypatch):
    monkeypatch.delenv(runtime.TURBO_ENV, raising=False)
    monkeypatch.delenv(runtime.MODEL_CACHE_ENV, raising=False)


def test_driver_compiler_is_always_requested():
    """The Ubuntu NPU packages only provide the compiler through the driver."""
    assert runtime.npu_properties()["NPU_COMPILER_TYPE"] == "DRIVER"


def test_defaults_are_lean():
    """Caching and turbo both cost the user something, so neither is implicit."""
    assert runtime.npu_properties() == {"NPU_COMPILER_TYPE": "DRIVER"}


def test_model_cache_is_off_until_asked(monkeypatch, tmp_path):
    """A 1.2 GB cache that saves 0.12s must never appear without consent."""
    monkeypatch.setattr(runtime, "MODEL_CACHE_DIR", tmp_path / "model-cache")
    assert "CACHE_DIR" not in runtime.npu_properties()
    assert not (tmp_path / "model-cache").exists()


def test_model_cache_opt_in_creates_the_directory(monkeypatch, tmp_path):
    cache = tmp_path / "model-cache"
    monkeypatch.setattr(runtime, "MODEL_CACHE_DIR", cache)
    monkeypatch.setenv(runtime.MODEL_CACHE_ENV, "1")
    assert runtime.npu_properties()["CACHE_DIR"] == str(cache)
    assert cache.is_dir()


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
def test_turbo_accepts_the_usual_spellings(monkeypatch, value):
    monkeypatch.setenv(runtime.TURBO_ENV, value)
    assert runtime.npu_properties()["NPU_TURBO"] is True


@pytest.mark.parametrize("value", ["0", "false", "no", "", "  "])
def test_turbo_stays_off_for_anything_else(monkeypatch, value):
    """An unset-looking value must not silently raise the machine's power draw."""
    monkeypatch.setenv(runtime.TURBO_ENV, value)
    assert "NPU_TURBO" not in runtime.npu_properties()


def test_overrides_win_over_defaults():
    """Callers need an escape hatch without reaching into module globals."""
    assert runtime.npu_properties(NPU_COMPILER_TYPE="MLIR")["NPU_COMPILER_TYPE"] == "MLIR"


def test_runtime_imports_nothing_heavy():
    """A top-level openvino import here would break the CI import check."""
    source = Path(runtime.__file__).read_text(encoding="utf-8")
    assert "import openvino" not in source


def test_no_directory_is_created_at_import_time(tmp_path):
    """Import-time mkdir would fire on `intel-npu-info` and in the CI import check."""
    home = tmp_path / "home"
    probe = (
        "import intel_npu_tools.runtime as r;"
        "print(r.MODEL_CACHE_DIR.exists())"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        env={**os.environ, "INTEL_NPU_TOOLS_HOME": str(home), "PYTHONPATH": str(SRC)},
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "False"
