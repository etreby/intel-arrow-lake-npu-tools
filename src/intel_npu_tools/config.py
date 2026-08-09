"""Persistent settings, so choices made in the control panel survive a restart.

Everything here was an environment variable first, and still is: a variable
always wins over the stored file. That ordering matters because the variables
are how a one-off run overrides a setting — `INTEL_NPU_TOOLS_WHISPER_MODEL=...
intel-npu-speech` has to keep working, and a benchmark that sets a variable per
subprocess must not be silently overruled by a file the user edited months ago.

Stdlib only, and never raises: a corrupt or unreadable settings file falls back
to defaults rather than stopping every command in the toolkit from starting.
"""

import json
import os
from pathlib import Path


# The toolkit's data directory is resolved here rather than in paths.py because
# paths.py needs settings to compute some of its own values, and settings live
# under the data directory. Putting the resolution at the bottom of the stack
# keeps that a straight line instead of a cycle; paths.py re-exports DATA_DIR,
# so nothing else has to know it moved.
DATA_DIR = Path(
    os.environ.get("INTEL_NPU_TOOLS_HOME", Path.home() / ".local/share/intel-arrow-lake-npu-tools")
).expanduser()

SETTINGS_FILE = DATA_DIR / "settings.json"

# Setting name -> environment variable that overrides it.
ENVIRONMENT = {
    "whisper_model": "INTEL_NPU_TOOLS_WHISPER_MODEL",
    "model_cache": "INTEL_NPU_TOOLS_MODEL_CACHE",
    "turbo": "INTEL_NPU_TOOLS_TURBO",
}
_TRUTHY = {"1", "true", "yes", "on"}


def load() -> dict:
    """Read the settings file, treating any problem as "no settings"."""
    try:
        stored = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return stored if isinstance(stored, dict) else {}


def save(settings: dict) -> None:
    """Write settings atomically, so an interrupted write cannot truncate them."""
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = SETTINGS_FILE.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(settings, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(SETTINGS_FILE)


def text(name: str, default: str = "") -> str:
    """Resolve a string setting: environment first, then file, then default."""
    variable = ENVIRONMENT.get(name)
    if variable:
        value = os.environ.get(variable, "").strip()
        if value:
            return value
    value = load().get(name)
    return value.strip() if isinstance(value, str) and value.strip() else default


def flag(name: str, default: bool = False) -> bool:
    """Resolve a boolean setting: environment first, then file, then default.

    An environment variable set to anything at all is an explicit answer,
    including "0", so it settles the question either way rather than falling
    through to the file when it happens to be false.
    """
    variable = ENVIRONMENT.get(name)
    if variable and variable in os.environ:
        return os.environ[variable].strip().lower() in _TRUTHY
    value = load().get(name)
    return bool(value) if isinstance(value, bool) else default


def update(name: str, value) -> dict:
    settings = load()
    settings[name] = value
    save(settings)
    return settings


def overridden(name: str) -> str | None:
    """The environment variable currently masking a setting, if any.

    The panel shows this, because a control that appears to do nothing is worse
    than one that explains why: a variable exported in the user's shell profile
    silently wins over anything the panel writes.
    """
    variable = ENVIRONMENT.get(name)
    if not variable:
        return None
    if name in ("model_cache", "turbo"):
        return variable if variable in os.environ else None
    return variable if os.environ.get(variable, "").strip() else None


def settings_path() -> Path:
    return SETTINGS_FILE
