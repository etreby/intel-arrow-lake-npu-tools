"""Keep every test away from the developer's own settings file.

Settings resolve from the environment first and the stored file second, so
without this a real `settings.json` under the user's data directory would leak
into the suite: a machine with `model_cache` enabled would fail the tests that
assert it is off by default, and the failure would look like a code defect
rather than local state.
"""

import pytest

from intel_npu_tools import config


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "settings.json")
    for variable in config.ENVIRONMENT.values():
        monkeypatch.delenv(variable, raising=False)
    yield
