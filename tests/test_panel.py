"""Cover the control panel.

Constructing Tk widgets needs a display, so the widget tests skip without one
and the continuous integration runner sees only the pure helpers. The parts
worth protecting either way are the ones that decide what the window offers:
a model picker must not list a model that is not installed, and the worker
plumbing must deliver a failure to the user rather than losing it in a thread.
"""

import os
import time

import pytest

from intel_npu_tools import config, panel


def _display() -> bool:
    """Whether a display can actually be opened, not merely whether one is named.

    Checking the variables alone is not enough: DISPLAY is routinely set to
    something unreachable — a stale value inherited by a sandbox, or an X server
    that refuses the connection because no authorization cookie came with it —
    and every widget test then fails on TclError instead of skipping, which
    reads as broken code rather than a machine without a display. Connecting
    once is the only honest test, so that is what this does.
    """
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return False
    try:
        import tkinter
    except ImportError:  # a Python built without Tk
        return False
    try:
        tkinter.Tk().destroy()
    except Exception:
        return False
    return True


needs_display = pytest.mark.skipif(not _display(), reason="constructing Tk widgets needs a display")


@pytest.fixture(autouse=True)
def no_modal_dialogs(monkeypatch):
    """Never let a test open a real dialog.

    messagebox.showerror is modal: it blocks the event loop until a human
    clicks it, which under a virtual display means the suite hangs forever
    rather than failing.
    """
    monkeypatch.setattr(panel.messagebox, "showerror", lambda *args, **kwargs: None)
    monkeypatch.setattr(panel.messagebox, "showinfo", lambda *args, **kwargs: None)


def pump(root, ready, timeout=8.0):
    """Run the event loop until `ready()` or the timeout.

    A bare `root.update()` loop is not enough: results are delivered from an
    `after` timer, so the loop has to actually let wall-clock time pass or the
    timer never fires and every worker looks like it produced nothing.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        root.update()
        if ready():
            return True
        time.sleep(0.02)
    return False


def test_model_choices_lists_only_installed_models(monkeypatch, tmp_path):
    """Offering a model that is not on disk produces a confusing failure later."""
    models = tmp_path / "models"
    (models / "whisper-base-int8-ov").mkdir(parents=True)
    (models / "whisper-small-int8-ov").mkdir()
    (models / "Qwen3-Embedding-0.6B-int8-ov").mkdir()
    (models / "not-a-directory.txt").write_text("x", encoding="utf-8")
    monkeypatch.setattr(panel, "MODEL_DIR", models)
    assert panel._model_choices() == ["whisper-base-int8-ov", "whisper-small-int8-ov"]


def test_model_choices_falls_back_when_nothing_is_installed(monkeypatch, tmp_path):
    """An empty picker would leave the user unable to pick anything at all."""
    monkeypatch.setattr(panel, "MODEL_DIR", tmp_path / "absent")
    assert panel._model_choices() == [panel.DEFAULT_WHISPER_MODEL]


@needs_display
def test_every_tab_is_present():
    import tkinter as tk

    root = tk.Tk()
    try:
        window = panel.Panel(root)
        names = [window.tabs.tab(index, "text") for index in range(window.tabs.index("end"))]
        assert names == ["Voice", "Screen", "Search", "Config", "Status"]
    finally:
        root.destroy()


@needs_display
def test_saving_a_setting_writes_it_to_the_settings_file():
    import tkinter as tk

    root = tk.Tk()
    try:
        window = panel.Panel(root)
        window.whisper_choice.set("whisper-small-int8-ov")
        window.save_whisper()
        assert config.load()["whisper_model"] == "whisper-small-int8-ov"
        window.cache_var.set(True)
        window.save_flag("model_cache", window.cache_var)
        assert config.load()["model_cache"] is True
    finally:
        root.destroy()


@needs_display
def test_an_overriding_variable_is_reported_to_the_user(monkeypatch):
    """A toggle that silently does nothing is the worst possible control."""
    import tkinter as tk

    monkeypatch.setenv("INTEL_NPU_TOOLS_TURBO", "1")
    root = tk.Tk()
    try:
        window = panel.Panel(root)
        window._refresh_overrides()
        assert "INTEL_NPU_TOOLS_TURBO" in window.override_note.cget("text")
    finally:
        root.destroy()


@needs_display
def test_a_failing_worker_reaches_the_user_instead_of_vanishing(monkeypatch):
    """An exception on a worker thread would otherwise be lost silently."""
    import tkinter as tk

    root = tk.Tk()
    try:
        window = panel.Panel(root)
        shown: list = []
        monkeypatch.setattr(panel.messagebox, "showerror", lambda title, message: shown.append((title, message)))

        def explode():
            raise RuntimeError("the NPU said no")

        window._run("Doing a thing", explode)
        assert pump(root, lambda: bool(shown)), "the failure never reached the user"
        assert shown and "the NPU said no" in shown[0][1]
        assert "failed" in window.status.get()
    finally:
        root.destroy()


@needs_display
def test_a_successful_worker_reports_its_duration():
    import tkinter as tk

    root = tk.Tk()
    try:
        window = panel.Panel(root)
        received: list = []
        window._run("Counting", lambda: 41 + 1, received.append)
        assert pump(root, lambda: bool(received)), "the result never arrived"
        assert received == [42]
        assert "done in" in window.status.get()
    finally:
        root.destroy()


@needs_display
def test_widget_updates_happen_on_the_main_thread():
    """Tk is not thread-safe; a worker touching widgets directly crashes at random.

    The worker below records which thread the callback runs on, which must be
    the one running the event loop rather than the thread that did the work.
    """
    import threading
    import tkinter as tk

    root = tk.Tk()
    try:
        window = panel.Panel(root)
        main = threading.get_ident()
        seen: list = []
        window._run("Checking threads", threading.get_ident, seen.append)
        assert pump(root, lambda: bool(seen)), "the callback never ran"
        assert seen and seen[0] != main, "the work itself must not run on the main thread"
        assert threading.get_ident() == main
    finally:
        root.destroy()


@needs_display
def test_a_failed_transcription_re_enables_the_record_button(monkeypatch):
    """One transient failure used to disable recording for the window's lifetime."""
    import tkinter as tk

    root = tk.Tk()
    try:
        window = panel.Panel(root)
        monkeypatch.setattr(panel.messagebox, "showerror", lambda *a, **k: None)
        window.record_button.configure(state="disabled")
        restored: list = []

        def explode():
            raise RuntimeError("no microphone")

        window._run("Transcribing", explode, always=lambda: restored.append(
            window.record_button.configure(state="normal")
        ))
        assert pump(root, lambda: bool(restored)), "the always callback never ran"
        assert str(window.record_button["state"]) == "normal"
    finally:
        root.destroy()


@needs_display
def test_always_runs_even_when_the_result_handler_raises(monkeypatch):
    """A bug in a done callback must not strand the window in a disabled state."""
    import tkinter as tk

    root = tk.Tk()
    try:
        window = panel.Panel(root)
        monkeypatch.setattr(panel.messagebox, "showerror", lambda *a, **k: None)
        cleaned: list = []

        def broken(_result):
            raise ValueError("bad handler")

        window._run("Working", lambda: 1, broken, lambda: cleaned.append(True))
        assert pump(root, lambda: bool(cleaned)), "cleanup was skipped when done raised"
    finally:
        root.destroy()
