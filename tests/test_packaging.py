"""Guard the packaging metadata.

Three packaging formats carry the version independently, and a release where
the .deb says 0.3.0 while the RPM says 0.2.1 is the kind of mistake nobody
notices until a user reports it. The desktop entries are checked here too
because a malformed one is silently ignored by the desktop rather than
reported.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PACKAGING = ROOT / "packaging"
DESKTOP_FILES = sorted(PACKAGING.glob("*.desktop.in"))


def project_version() -> str:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    return re.search(r'^version = "(.+)"', text, re.M).group(1)


def test_pkgbuild_version_matches_the_project():
    text = (PACKAGING / "PKGBUILD").read_text(encoding="utf-8")
    assert re.search(r"^pkgver=(.+)$", text, re.M).group(1) == project_version()


def test_rpm_spec_version_matches_the_project():
    text = (PACKAGING / "intel-npu-tools.spec").read_text(encoding="utf-8")
    assert re.search(r"^Version:\s*(\S+)$", text, re.M).group(1) == project_version()


@pytest.mark.parametrize("path", DESKTOP_FILES, ids=lambda p: p.name)
def test_desktop_entries_are_well_formed(path):
    lines = path.read_text(encoding="utf-8").splitlines()
    entries = dict(
        line.split("=", 1) for line in lines if "=" in line and not line.startswith("#")
    )
    assert lines[0] == "[Desktop Entry]"
    assert entries["Type"] == "Application"
    assert entries["Exec"].startswith("@BINDIR@/"), "packages and install.sh both substitute @BINDIR@"
    assert entries["Icon"] == "intel-npu-tools", "the icon is installed under this name"
    assert entries["Categories"].endswith(";")


@pytest.mark.parametrize("path", DESKTOP_FILES, ids=lambda p: p.name)
def test_only_one_main_category_per_entry(path):
    """Two main categories make the application appear twice in the menu."""
    main = {
        "AudioVideo", "Audio", "Video", "Development", "Education", "Game",
        "Graphics", "Network", "Office", "Science", "Settings", "System", "Utility",
    }
    text = path.read_text(encoding="utf-8")
    categories = re.search(r"^Categories=(.+)$", text, re.M).group(1)
    assert len([c for c in categories.split(";") if c in main]) == 1


def test_every_shipped_command_has_a_wrapper_and_an_entry_point():
    """A command in one list and not the other is installed but unrunnable."""
    staged = (ROOT / "scripts" / "stage-package.sh").read_text(encoding="utf-8")
    commands = set(re.search(r"^COMMANDS=\((.+?)\)$", staged, re.M).group(1).split())
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    scripts = set(re.findall(r"^(intel-npu-[\w-]+) = ", pyproject, re.M))
    assert commands == scripts
