"""Cover persistent settings and their precedence over the environment.

The ordering is the whole point: the control panel writes the file, but a
one-off `INTEL_NPU_TOOLS_WHISPER_MODEL=... intel-npu-speech` has to keep
winning, and `scripts/benchmark.py` sets variables per subprocess to measure
configurations the file does not hold.
"""

import json

import pytest

from intel_npu_tools import config, paths, runtime


def test_missing_file_reads_as_no_settings():
    assert config.load() == {}


def test_a_saved_setting_is_read_back():
    config.update("whisper_model", "whisper-small-int8-ov")
    assert config.text("whisper_model") == "whisper-small-int8-ov"


def test_the_environment_beats_the_file(monkeypatch):
    """A one-off override on the command line must not be overruled by a file."""
    config.update("whisper_model", "whisper-small-int8-ov")
    monkeypatch.setenv("INTEL_NPU_TOOLS_WHISPER_MODEL", "whisper-base-int8-ov")
    assert config.text("whisper_model") == "whisper-base-int8-ov"


def test_a_false_environment_flag_still_beats_a_true_file(monkeypatch):
    """Turning something off for one run has to work even when the file says on."""
    config.update("model_cache", True)
    assert config.flag("model_cache") is True
    monkeypatch.setenv("INTEL_NPU_TOOLS_MODEL_CACHE", "0")
    assert config.flag("model_cache") is False


def test_flags_default_off_with_no_file_and_no_variable():
    assert config.flag("model_cache") is False
    assert config.flag("turbo") is False


def test_corrupt_settings_fall_back_rather_than_raising():
    """Every command in the toolkit imports this; it cannot refuse to start."""
    config.SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    config.SETTINGS_FILE.write_text("{not json at all", encoding="utf-8")
    assert config.load() == {}
    assert config.text("whisper_model", "fallback") == "fallback"


def test_a_settings_file_that_is_not_an_object_is_ignored():
    config.SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    config.SETTINGS_FILE.write_text("[1, 2, 3]", encoding="utf-8")
    assert config.load() == {}


def test_saving_is_atomic_and_leaves_no_temporary_file():
    config.update("turbo", True)
    assert json.loads(config.SETTINGS_FILE.read_text())["turbo"] is True
    assert not list(config.SETTINGS_FILE.parent.glob("*.tmp"))


def test_overridden_names_the_masking_variable(monkeypatch):
    """A control that silently does nothing is worse than one that explains."""
    assert config.overridden("whisper_model") is None
    monkeypatch.setenv("INTEL_NPU_TOOLS_WHISPER_MODEL", "whisper-small-int8-ov")
    assert config.overridden("whisper_model") == "INTEL_NPU_TOOLS_WHISPER_MODEL"


def test_overridden_reports_a_flag_set_to_false(monkeypatch):
    """`FOO=0` is still an override; the panel must say the toggle is inert."""
    monkeypatch.setenv("INTEL_NPU_TOOLS_MODEL_CACHE", "0")
    assert config.overridden("model_cache") == "INTEL_NPU_TOOLS_MODEL_CACHE"


def test_runtime_flags_follow_the_settings_file():
    config.update("turbo", True)
    assert runtime.turbo_enabled() is True
    assert runtime.npu_properties()["NPU_TURBO"] is True


def test_model_cache_setting_reaches_the_plugin_properties(monkeypatch, tmp_path):
    monkeypatch.setattr(runtime, "MODEL_CACHE_DIR", tmp_path / "model-cache")
    config.update("model_cache", True)
    assert "CACHE_DIR" in runtime.npu_properties()


@pytest.mark.parametrize("value", ["../../etc", "/etc/passwd", "..", ".", "a/b/.."])
def test_a_stored_whisper_name_cannot_escape_the_model_directory(value):
    """The file is user-editable, so it gets the same guard as the variable.

    The guarantee is containment, not rejection: "/etc/passwd" reduces to the
    single name "passwd", which resolves inside the models directory and simply
    will not load. What must never happen is a value resolving outside it.
    """
    config.update("whisper_model", value)
    name = paths._model_directory_name(
        config.text("whisper_model", paths.DEFAULT_WHISPER_MODEL), paths.DEFAULT_WHISPER_MODEL
    )
    resolved = paths.MODEL_DIR / name
    assert name not in ("", ".", "..") and paths.os.sep not in name
    assert resolved.parent == paths.MODEL_DIR
    assert ".." not in resolved.parts
