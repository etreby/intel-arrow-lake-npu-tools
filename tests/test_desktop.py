"""Cover desktop integration across compositors.

Screenshots and the clipboard were written against KDE's tools, which do not
exist on GNOME or COSMIC, so the OCR features failed outright there. These
tests fake the tool lookup rather than requiring any of them to be installed,
because the point is the selection and fallback logic.
"""

import subprocess

import pytest

from intel_npu_tools import desktop


@pytest.fixture
def installed(monkeypatch):
    """Pretend a chosen set of tools exists."""

    def use(*tools):
        present = set(tools)
        monkeypatch.setattr(desktop.shutil, "which", lambda tool: tool if tool in present else None)

    return use


def test_the_desktops_own_tool_is_preferred(installed, monkeypatch):
    """On GNOME, gnome-screenshot should win even though grim is also present."""
    installed("grim", "gnome-screenshot", "maim")
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "GNOME")
    assert desktop.capture_backends()[0] == "gnome-screenshot"


def test_cosmic_is_recognised(installed, monkeypatch):
    installed("cosmic-screenshot", "maim")
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "COSMIC")
    assert desktop.capture_backends()[0] == "cosmic-screenshot"


def test_a_compound_desktop_string_is_handled(installed, monkeypatch):
    """XDG_CURRENT_DESKTOP often lists several, such as "pop:GNOME"."""
    installed("gnome-screenshot", "spectacle")
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "pop:GNOME")
    assert desktop.capture_backends()[0] == "gnome-screenshot"


def test_generic_tools_still_work_on_an_unknown_desktop(installed, monkeypatch):
    installed("maim")
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "SomethingNobodyHasHeardOf")
    assert desktop.capture_backends() == ["maim"]


def test_no_screenshot_tool_names_what_to_install(installed, tmp_path):
    installed()
    with pytest.raises(desktop.CaptureUnavailable, match="gnome-screenshot"):
        desktop.capture(tmp_path / "shot.png")


def test_a_failing_backend_falls_through_to_the_next(installed, monkeypatch, tmp_path):
    """A tool can be installed and still fail, e.g. a Wayland helper under X11."""
    installed("spectacle", "maim")
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE")
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command[0])
        if command[0] == "spectacle":
            raise subprocess.CalledProcessError(1, command)
        target = tmp_path / "shot.png"
        target.write_bytes(b"\x89PNG fake")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(desktop, "_run", fake_run)
    assert desktop.capture(tmp_path / "shot.png").is_file()
    assert calls == ["spectacle", "maim"]


def test_an_empty_image_counts_as_failure(installed, monkeypatch, tmp_path):
    """A backend that exits cleanly having written nothing must not be trusted."""
    installed("maim")
    monkeypatch.setattr(desktop, "_run", lambda command, **kwargs: subprocess.CompletedProcess(command, 0))
    (tmp_path / "shot.png").write_bytes(b"")
    with pytest.raises(desktop.CaptureUnavailable, match="produced no image"):
        desktop.capture(tmp_path / "shot.png")


def test_wayland_clipboard_is_preferred(installed, monkeypatch):
    installed("wl-copy", "xclip")
    used = []
    monkeypatch.setattr(desktop, "_run", lambda command, **kwargs: used.append(command[0]) or subprocess.CompletedProcess(command, 0))
    assert desktop.copy_text("hello") == "wl-copy"
    assert used == ["wl-copy"]


def test_x11_clipboard_is_used_when_wayland_is_absent(installed, monkeypatch):
    installed("xclip")
    received = {}

    def fake_run(command, **kwargs):
        received["command"] = command
        received["input"] = kwargs.get("input")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(desktop, "_run", fake_run)
    assert desktop.copy_text("hello") == "xclip"
    # The X11 tools read stdin, unlike wl-copy which takes an argument.
    assert received["input"] == b"hello"


def test_no_clipboard_tool_names_what_to_install(installed):
    installed()
    with pytest.raises(desktop.ClipboardUnavailable, match="wl-clipboard"):
        desktop.copy_text("hello")


def test_summary_reports_what_the_session_can_do(installed, monkeypatch):
    installed("grim", "wl-copy")
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "sway")
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    report = desktop.summary()
    assert report["capture"] == ["grim"]
    assert report["clipboard"] == ["wl-copy"]
    assert report["session"] == "wayland"


def test_a_stale_image_is_not_credited_to_the_next_backend(installed, monkeypatch, tmp_path):
    """A backend that half-wrote and failed must not make the next one look good."""
    installed("spectacle", "maim")
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE")
    target = tmp_path / "shot.png"

    def fake_run(command, **kwargs):
        if command[0] == "spectacle":
            target.write_bytes(b"partial junk")           # writes, then fails
            raise subprocess.CalledProcessError(1, command)
        return subprocess.CompletedProcess(command, 0)     # succeeds, writes nothing

    monkeypatch.setattr(desktop, "_run", fake_run)
    with pytest.raises(desktop.CaptureUnavailable, match="produced no image"):
        desktop.capture(target)


def test_the_focused_monitor_is_captured_not_the_whole_desktop(installed, monkeypatch, tmp_path):
    """--fullscreen would grab every monitor: more tokens, and screens the user
    was not looking at handed to an agent."""
    installed("spectacle")
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE")
    seen: list = []

    def fake_run(command, **kwargs):
        seen.append(command)
        (tmp_path / "shot.png").write_bytes(b"\x89PNG")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(desktop, "_run", fake_run)
    desktop.capture(tmp_path / "shot.png", region=False)
    assert "--current" in seen[0] and "--fullscreen" not in seen[0]
    seen.clear()
    desktop.capture(tmp_path / "shot.png", region=True)
    assert "--region" in seen[0]
