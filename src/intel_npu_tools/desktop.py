"""Desktop integration that is not tied to one Wayland compositor.

Screenshots and the clipboard are the only two places this toolkit has to talk
to the desktop, and both were written for KDE: `spectacle` for capture and
`wl-copy` for the clipboard. Spectacle does not exist on GNOME or COSMIC, so
the OCR features simply failed there.

Each capability is a list of backends tried in order, preferring whichever
matches the running desktop. They are genuinely different shapes rather than
one command with different names — spectacle writes to a path you give it,
cosmic-screenshot writes into a directory and tells you what it chose, and grim
needs a separate program to select a region — so each is a small function
rather than an argument table.

Stdlib only, so importing this never drags in an inference stack.
"""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path


TIMEOUT = 60


class CaptureUnavailable(RuntimeError):
    """No screenshot backend is installed for this desktop."""


class ClipboardUnavailable(RuntimeError):
    """No clipboard backend is installed for this session."""


def desktop_names() -> list[str]:
    """Lower-case desktop identifiers from XDG_CURRENT_DESKTOP, which may list several."""
    raw = os.environ.get("XDG_CURRENT_DESKTOP", "")
    return [part.strip().lower() for part in raw.split(":") if part.strip()]


def _run(command: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(command, timeout=TIMEOUT, **kwargs)


# --------------------------------------------------------------------- capture


def _spectacle(target: Path, region: bool) -> Path:
    # --current, not --fullscreen: it takes the monitor the pointer is on. On a
    # multi-monitor desk --fullscreen returns the whole virtual desktop, which
    # both costs far more tokens to read and puts screens the user was not
    # looking at in front of an agent.
    mode = "--region" if region else "--current"
    _run(["spectacle", mode, "--background", "--nonotify", "--output", str(target)], check=True)
    return target


def _gnome_screenshot(target: Path, region: bool) -> Path:
    command = ["gnome-screenshot", "-f", str(target)]
    if region:
        command.insert(1, "-a")
    _run(command, check=True)
    return target


def _cosmic_screenshot(target: Path, region: bool) -> Path:
    """COSMIC saves into a directory and prints the file it created.

    Interactive mode is the only way to pick a region, and it returns whatever
    the user selected; non-interactive grabs the whole screen.
    """
    with tempfile.TemporaryDirectory(prefix="intel-npu-shot-") as folder:
        result = _run(
            [
                "cosmic-screenshot",
                f"--interactive={'true' if region else 'false'}",
                "--notify=false",
                "--save-dir",
                folder,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        produced = Path(result.stdout.strip()) if result.stdout.strip() else None
        if produced is None or not produced.is_file():
            candidates = sorted(Path(folder).glob("*"))
            if not candidates:
                raise CaptureUnavailable("cosmic-screenshot produced no file")
            produced = candidates[-1]
        shutil.copyfile(produced, target)
    return target


def _grim(target: Path, region: bool) -> Path:
    """wlroots compositors: sway, Hyprland, river. Region needs slurp."""
    command = ["grim"]
    if region:
        if not shutil.which("slurp"):
            raise CaptureUnavailable("grim needs slurp to select a region")
        geometry = _run(["slurp"], check=True, capture_output=True, text=True).stdout.strip()
        if not geometry:
            raise CaptureUnavailable("no region was selected")
        command += ["-g", geometry]
    command.append(str(target))
    _run(command, check=True)
    return target


def _maim(target: Path, region: bool) -> Path:
    command = ["maim"] + (["-s"] if region else []) + [str(target)]
    _run(command, check=True)
    return target


def _scrot(target: Path, region: bool) -> Path:
    command = ["scrot"] + (["-s"] if region else []) + ["-o", str(target)]
    _run(command, check=True)
    return target


def _import_magick(target: Path, region: bool) -> Path:
    command = ["import"] + ([] if region else ["-window", "root"]) + [str(target)]
    _run(command, check=True)
    return target


# (tool, desktop hints it belongs to, function)
CAPTURE_BACKENDS = (
    ("spectacle", ("kde", "plasma"), _spectacle),
    ("cosmic-screenshot", ("cosmic", "pop"), _cosmic_screenshot),
    ("gnome-screenshot", ("gnome", "unity", "ubuntu"), _gnome_screenshot),
    ("grim", ("sway", "hyprland", "river", "wlroots"), _grim),
    ("maim", (), _maim),
    ("scrot", (), _scrot),
    ("import", (), _import_magick),
)


def capture_backends() -> list[str]:
    """Installed screenshot tools, best match for this desktop first."""
    current = set(desktop_names())
    installed = [(tool, hints) for tool, hints, _ in CAPTURE_BACKENDS if shutil.which(tool)]
    installed.sort(key=lambda item: 0 if current & set(item[1]) else 1)
    return [tool for tool, _ in installed]


def capture(target: Path, region: bool = False) -> Path:
    """Screenshot the whole screen, or a selected region, into target.

    Backends are tried in order so that a tool which is installed but broken —
    a Wayland compositor's helper invoked from an X11 session, say — does not
    make the feature unavailable when another one would have worked.
    """
    target = Path(target)
    current = set(desktop_names())
    ordered = [entry for entry in CAPTURE_BACKENDS if shutil.which(entry[0])]
    ordered.sort(key=lambda entry: 0 if current & set(entry[1]) else 1)
    if not ordered:
        raise CaptureUnavailable(
            "No screenshot tool found. Install one of: spectacle (KDE), "
            "gnome-screenshot (GNOME), cosmic-screenshot (COSMIC), grim (sway/Hyprland), "
            "or maim/scrot on X11."
        )
    failures = []
    for tool, _hints, function in ordered:
        # Clear the target first. A backend that writes a partial image and then
        # fails would otherwise leave a non-empty file behind, and the next
        # backend — succeeding without writing anything — would have that stale
        # image accepted as its own output.
        try:
            target.unlink()
        except OSError:
            pass
        try:
            produced = function(target, region)
        except (OSError, subprocess.SubprocessError, CaptureUnavailable) as exc:
            failures.append(f"{tool}: {exc}")
            continue
        if produced.is_file() and produced.stat().st_size:
            return produced
        failures.append(f"{tool}: produced no image")
    raise CaptureUnavailable("Every screenshot backend failed — " + "; ".join(failures))


# ------------------------------------------------------------------- clipboard

CLIPBOARD_BACKENDS = (
    ("wl-copy", ["wl-copy", "--"]),
    ("xclip", ["xclip", "-selection", "clipboard"]),
    ("xsel", ["xsel", "--clipboard", "--input"]),
)


def clipboard_backends() -> list[str]:
    return [tool for tool, _ in CLIPBOARD_BACKENDS if shutil.which(tool)]


def copy_text(text: str) -> str:
    """Put text on the clipboard, returning the backend that accepted it.

    wl-copy takes the text as an argument and the X11 tools read stdin, which is
    why this passes it both ways rather than sharing one invocation.
    """
    for tool, command in CLIPBOARD_BACKENDS:
        if not shutil.which(tool):
            continue
        try:
            if tool == "wl-copy":
                _run(command + [text], check=True)
            else:
                _run(command, input=text.encode("utf-8"), check=True)
        except (OSError, subprocess.SubprocessError):
            continue
        return tool
    raise ClipboardUnavailable(
        "No clipboard tool found. Install wl-clipboard on Wayland, or xclip or xsel on X11."
    )


def summary() -> dict:
    """What this session can actually do, for the panel's diagnostics."""
    return {
        "desktop": os.environ.get("XDG_CURRENT_DESKTOP", "unknown"),
        "session": os.environ.get("XDG_SESSION_TYPE", "unknown"),
        "capture": capture_backends(),
        "clipboard": clipboard_backends(),
    }
