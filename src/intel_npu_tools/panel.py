"""A control panel for exercising and configuring the whole toolkit.

The two focused applications stay as they are: `intel-npu-speech` and
`intel-npu-ocr` exist to do one thing quickly from a keyboard shortcut, and
putting a tabbed window behind those shortcuts would make dictation slower for
no benefit. This is the other shape — somewhere to try every feature, see what
the NPU is actually doing, and change the settings that were previously
environment variables only.

Every operation that touches the NPU runs on a worker thread. Compiling a model
takes seconds and transcription takes tenths of one, which is long enough that
doing it on the Tk main loop would freeze the window mid-click.
"""

import json
import os
import queue
import signal
import subprocess
import tempfile
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import config
from .desktop import capture, clipboard_backends, copy_text, summary
from .paths import (
    DATA_DIR,
    DEFAULT_WHISPER_MODEL,
    EMBEDDING_MODEL,
    MODEL_DIR,
    OCR_MODEL_DIR,
    RERANK_MODEL,
    SEMANTIC_DB,
    WHISPER_MODEL,
)


BACKGROUND = "#181a1f"
SURFACE = "#22252b"
FOREGROUND = "#eef1f6"
MUTED = "#9aa3b2"
ACCENT = "#4c8dff"
WARN = "#e0a33e"


def _model_choices() -> list[str]:
    """Whisper directories actually present, so the picker cannot offer a lie."""
    try:
        found = sorted(
            entry.name
            for entry in MODEL_DIR.iterdir()
            if entry.is_dir() and entry.name.startswith("whisper-")
        )
    except OSError:
        found = []
    return found or [DEFAULT_WHISPER_MODEL]


class Panel:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.recorder = None
        self.audio_path = None
        self.events: queue.Queue = queue.Queue()
        root.title("Intel NPU Control Panel")
        root.geometry("940x680")
        root.minsize(760, 560)
        root.configure(bg=BACKGROUND)
        self._style()

        outer = ttk.Frame(root, padding=(18, 14))
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="Intel NPU Control Panel", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            outer,
            text="Exercise and configure every part of the toolkit on Intel AI Boost",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(2, 12))

        # The status line and its spinner are built before the tabs, because a
        # tab may start work as soon as it is created and _run touches both.
        self.status = tk.StringVar(value="Ready")
        bar = ttk.Frame(outer)
        self.busy = ttk.Progressbar(bar, mode="indeterminate", length=140)

        self.tabs = ttk.Notebook(outer)
        self.tabs.pack(fill="both", expand=True)
        self._voice_tab()
        self._screen_tab()
        self._search_tab()
        self._config_tab()
        self._status_tab()

        # Packed last so it settles beneath the notebook.
        bar.pack(fill="x", pady=(10, 0))
        ttk.Label(bar, textvariable=self.status, style="Muted.TLabel").pack(side="left")

        root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(80, self._drain)

    # ---------------------------------------------------------------- chrome

    def _style(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(".", background=BACKGROUND, foreground=FOREGROUND)
        style.configure("TFrame", background=BACKGROUND)
        style.configure("TLabel", background=BACKGROUND, foreground=FOREGROUND)
        style.configure("Title.TLabel", font=("Sans", 17, "bold"))
        style.configure("Heading.TLabel", font=("Sans", 11, "bold"))
        style.configure("Muted.TLabel", foreground=MUTED)
        style.configure("Warn.TLabel", foreground=WARN)
        style.configure("TButton", padding=8)
        style.configure("TCheckbutton", background=BACKGROUND, foreground=FOREGROUND)
        style.map("TCheckbutton", background=[("active", BACKGROUND)])
        style.configure("TNotebook", background=BACKGROUND, borderwidth=0)
        style.configure("TNotebook.Tab", padding=(16, 8))
        # A combobox draws its text through the "readonly" state rather than the
        # base configuration, so styling only the base leaves the selected value
        # in the theme's default grey-on-grey and effectively unreadable. The
        # dropdown itself is a plain Tk listbox and takes its colours from the
        # option database instead of from ttk at all.
        style.configure(
            "TCombobox",
            fieldbackground=SURFACE,
            background=SURFACE,
            foreground=FOREGROUND,
            arrowcolor=FOREGROUND,
            bordercolor=MUTED,
            lightcolor=SURFACE,
            darkcolor=SURFACE,
        )
        # A readonly combobox renders its value as *selected* text, so when it
        # takes focus the selection colours win over fieldbackground and the
        # field flips to the theme's light default. Every focus state has to be
        # pinned, not just "readonly", or the widget turns white on click.
        style.map(
            "TCombobox",
            fieldbackground=[
                ("readonly", "focus", SURFACE),
                ("readonly", SURFACE),
                ("disabled", BACKGROUND),
            ],
            foreground=[
                ("readonly", "focus", FOREGROUND),
                ("readonly", FOREGROUND),
                ("disabled", MUTED),
            ],
            selectbackground=[("readonly", "focus", SURFACE), ("readonly", SURFACE)],
            selectforeground=[("readonly", "focus", FOREGROUND), ("readonly", FOREGROUND)],
            arrowcolor=[("readonly", FOREGROUND)],
        )
        self.root.option_add("*TCombobox*Listbox.background", SURFACE)
        self.root.option_add("*TCombobox*Listbox.foreground", FOREGROUND)
        self.root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
        self.root.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")
        style.configure("TEntry", fieldbackground=SURFACE, foreground=FOREGROUND, insertcolor=FOREGROUND)
        # The check indicator is a separate element; without this it stays the
        # theme's light grey and reads as an unchecked box even when ticked.
        style.configure("TCheckbutton", indicatorcolor=SURFACE, focuscolor=BACKGROUND)
        style.map(
            "TCheckbutton",
            indicatorcolor=[("selected", ACCENT), ("!selected", SURFACE)],
            foreground=[("disabled", MUTED)],
        )

    def _text(self, parent, height=12) -> tk.Text:
        widget = tk.Text(
            parent,
            wrap="word",
            height=height,
            font=("Monospace", 10),
            bg=SURFACE,
            fg=FOREGROUND,
            insertbackground="white",
            relief="flat",
            padx=10,
            pady=8,
        )
        widget.pack(fill="both", expand=True, pady=(8, 0))
        return widget

    def _tab(self, title: str) -> ttk.Frame:
        frame = ttk.Frame(self.tabs, padding=16)
        self.tabs.add(frame, text=title)
        return frame

    # ------------------------------------------------------------- threading

    def _run(self, description: str, work, done=None, always=None):
        """Run work off the main loop and deliver its result back on it.

        `always` runs whether the work succeeded or failed, and exists because
        anything that disables a control before starting has to re-enable it
        afterwards. Without it a single transient failure — an unplugged
        microphone, a model that will not compile — left the record button
        disabled for the lifetime of the window.
        """
        self.status.set(description)
        self.busy.pack(side="right")
        self.busy.start(12)

        def worker():
            started = time.perf_counter()
            try:
                result = work()
                self.events.put(("ok", description, time.perf_counter() - started, result, done, always))
            except Exception as exc:  # surfaced in the UI rather than a traceback
                self.events.put(("error", description, time.perf_counter() - started, exc, done, always))

        threading.Thread(target=worker, daemon=True).start()

    def _drain(self):
        try:
            while True:
                kind, description, elapsed, payload, done, always = self.events.get_nowait()
                self.busy.stop()
                self.busy.pack_forget()
                try:
                    if kind == "ok":
                        self.status.set(f"{description} — done in {elapsed:.2f}s")
                        if done:
                            done(payload)
                    else:
                        self.status.set(f"{description} — failed")
                        messagebox.showerror(description, str(payload))
                finally:
                    # Runs even if `done` itself raises, so a bug in a result
                    # handler cannot leave the window in a disabled state.
                    if always:
                        always()
        except queue.Empty:
            pass
        self.root.after(80, self._drain)

    @staticmethod
    def _show(widget: tk.Text, content: str):
        widget.delete("1.0", "end")
        widget.insert("1.0", content)

    def _copy(self, content: str):
        if not content:
            return
        try:
            self.status.set(f"Copied to the clipboard using {copy_text(content)}")
        except Exception as exc:
            messagebox.showerror("Clipboard unavailable", str(exc))

    # ------------------------------------------------------------------ voice

    def _voice_tab(self):
        tab = self._tab("Voice")
        row = ttk.Frame(tab)
        row.pack(fill="x")
        self.record_button = ttk.Button(row, text="Start recording", command=self.toggle_record)
        self.record_button.pack(side="left")
        ttk.Button(row, text="Transcribe a file…", command=self.transcribe_file).pack(side="left", padx=8)
        ttk.Button(row, text="Copy", command=lambda: self._copy(self.voice_out.get("1.0", "end").strip())).pack(side="left")
        self.model_text = tk.StringVar(value=f"model: {WHISPER_MODEL.name}")
        ttk.Label(row, textvariable=self.model_text, style="Muted.TLabel").pack(side="right")
        self.voice_out = self._text(tab)
        ttk.Label(
            tab,
            text="Recording uses the system default microphone. Transcription runs on the NPU.",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(8, 0))

    def toggle_record(self):
        if self.recorder is None:
            handle = tempfile.NamedTemporaryFile(prefix="intel-npu-panel-", suffix=".wav", delete=False)
            handle.close()
            self.audio_path = handle.name
            self.recorder = subprocess.Popen(
                ["pw-record", "--rate", "16000", "--channels", "1", "--format", "s16", self.audio_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            self.record_button.configure(text="Stop and transcribe")
            self.status.set("Recording…")
            return
        recorder, self.recorder = self.recorder, None
        os.killpg(recorder.pid, signal.SIGINT)
        recorder.wait(timeout=5)
        self.record_button.configure(text="Start recording", state="disabled")
        path = self.audio_path

        def work():
            from .audio import decode_audio, transcribe

            return transcribe(decode_audio(Path(path)))

        def done(result):
            self._show(self.voice_out, result)
            self._copy(result)

        def always():
            self.record_button.configure(state="normal")
            self._discard_recording()

        self._run("Transcribing on the NPU", work, done, always)

    def transcribe_file(self):
        chosen = filedialog.askopenfilename(
            title="Choose an audio file",
            filetypes=[("Audio", "*.wav *.mp3 *.m4a *.flac *.ogg *.webm *.opus"), ("All files", "*")],
        )
        if not chosen:
            return

        def work():
            from .audio import transcribe_file

            return transcribe_file(Path(chosen))

        self._run(f"Transcribing {Path(chosen).name}", work, lambda r: self._show(self.voice_out, r))

    def _discard_recording(self):
        if not self.audio_path:
            return
        try:
            os.unlink(self.audio_path)
        except OSError:
            pass
        self.audio_path = None

    # ----------------------------------------------------------------- screen

    def _screen_tab(self):
        tab = self._tab("Screen")
        row = ttk.Frame(tab)
        row.pack(fill="x")
        ttk.Button(row, text="Capture monitor", command=lambda: self.read_screen(None)).pack(side="left")
        ttk.Button(row, text="Read an image…", command=self.read_image).pack(side="left", padx=8)
        ttk.Label(row, text="detail:", style="Muted.TLabel").pack(side="left", padx=(12, 4))
        self.detail = tk.StringVar(value="lines")
        ttk.Combobox(row, textvariable=self.detail, values=["text", "lines", "words"], width=8, state="readonly").pack(side="left")
        ttk.Button(row, text="Copy", command=lambda: self._copy(self.screen_out.get("1.0", "end").strip())).pack(side="right")
        self.screen_out = self._text(tab)
        ttk.Label(
            tab,
            text=(
                "screen_to_text reads with Tesseract, not the NPU, and reports widget text only — "
                "no widget type, state, or anything off-screen. Prefer a browser's accessibility "
                "tree for web pages."
            ),
            style="Muted.TLabel",
            wraplength=860,
            justify="left",
        ).pack(anchor="w", pady=(8, 0))

    def read_image(self):
        chosen = filedialog.askopenfilename(
            title="Choose an image",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff"), ("All files", "*")],
        )
        if chosen:
            self.read_screen(Path(chosen))

    def read_screen(self, path):
        detail = self.detail.get()

        def work():
            from .ocr import capture_current_monitor, structured_text

            if path is not None:
                return structured_text(path, detail)
            with tempfile.NamedTemporaryFile(prefix="intel-npu-panel-", suffix=".png") as image:
                return structured_text(capture_current_monitor(Path(image.name)), detail)

        def done(result):
            stats = result["stats"]
            head = (
                f"{stats['lines']} lines, {stats['words']} words, {stats['pages']} page(s)\n"
                f"~{stats['estimated_tokens']} tokens vs ~{stats['estimated_image_tokens_avoided']} "
                f"as an image\n\n"
            )
            body = result.get("text") or "\n".join(
                f"{line['bbox']}  conf={line['conf']:3d}  {line['text']}" for line in result["lines"]
            )
            self._show(self.screen_out, head + body + "\n\n" + "\n".join(result["warnings"]))

        self._run("Reading the screen", work, done)

    # ----------------------------------------------------------------- search

    def _search_tab(self):
        tab = self._tab("Search")
        index_row = ttk.Frame(tab)
        index_row.pack(fill="x")
        ttk.Button(index_row, text="Index a folder…", command=self.index_folder).pack(side="left")
        ttk.Button(index_row, text="Filter a file…", command=self.filter_file).pack(side="left", padx=8)
        self.rerank = tk.BooleanVar(value=False)
        self.rerank_box = ttk.Checkbutton(index_row, text="rerank", variable=self.rerank)
        self.rerank_box.pack(side="right")
        if not RERANK_MODEL.is_dir():
            self.rerank_box.configure(state="disabled")

        query_row = ttk.Frame(tab)
        query_row.pack(fill="x", pady=(10, 0))
        self.query = tk.StringVar()
        entry = ttk.Entry(query_row, textvariable=self.query)
        entry.pack(side="left", fill="x", expand=True)
        entry.bind("<Return>", lambda _event: self.search())
        ttk.Button(query_row, text="Search", command=self.search).pack(side="left", padx=(8, 0))
        self.search_out = self._text(tab)
        note = "Reranking re-scores the top passages with a cross-encoder."
        if not RERANK_MODEL.is_dir():
            note += "  Not installed — run scripts/download-models.py --with-reranker."
        ttk.Label(tab, text=note, style="Muted.TLabel", wraplength=860, justify="left").pack(anchor="w", pady=(8, 0))

    def index_folder(self):
        chosen = filedialog.askdirectory(title="Choose a folder to index")
        if not chosen:
            return

        def work():
            from .semantic import SemanticIndex

            return SemanticIndex().index(chosen)

        self._run(f"Indexing {Path(chosen).name}", work, lambda r: self._show(self.search_out, json.dumps(r, indent=2)))

    def search(self):
        query = self.query.get().strip()
        if not query:
            return
        rerank = self.rerank.get()

        def work():
            from .semantic import SemanticIndex

            return SemanticIndex().search(query, 8, None, rerank or None)

        def done(hits):
            if not hits:
                self._show(self.search_out, "No matches. Index a folder first, or try other words.")
                return
            lines = []
            for hit in hits:
                score = f"cos={hit['score']:.3f}"
                if "rerank_score" in hit:
                    score += f"  rerank={hit['rerank_score']:+.2f}"
                lines.append(f"{score}  {hit['path']}:{hit['start_line']}-{hit['end_line']}")
                lines.append("    " + hit["text"].strip().replace("\n", "\n    ")[:400])
                lines.append("")
            self._show(self.search_out, "\n".join(lines))

        self._run("Searching on the NPU", work, done)

    def filter_file(self):
        chosen = filedialog.askopenfilename(title="Choose a large text file to filter")
        if not chosen:
            return
        query = self.query.get().strip()
        if not query:
            messagebox.showinfo("A question is needed", "Type what you are looking for in the query box first.")
            return

        def work():
            from .context_filter import filter_context

            return filter_context(chosen, query)

        def done(result):
            head = (
                f"{result['input']['lines']} lines in, {result['returned']['lines']} out — "
                f"{result['returned']['reduction']} fewer tokens "
                f"(~{result['input']['estimated_tokens']} to ~{result['returned']['estimated_tokens']})\n"
                f"{result['dropped']['note']}\n\n"
            )
            body = "\n\n".join(
                f"lines {span['start_line']}-{span['end_line']}  score={span['score']:.3f}\n{span['text']}"
                for span in result["spans"]
            )
            self._show(self.search_out, head + body)

        self._run(f"Filtering {Path(chosen).name}", work, done)

    # ----------------------------------------------------------------- config

    def _config_tab(self):
        tab = self._tab("Config")
        ttk.Label(tab, text="Speech model", style="Heading.TLabel").pack(anchor="w")
        row = ttk.Frame(tab)
        row.pack(fill="x", pady=(4, 2))
        self.whisper_choice = tk.StringVar(value=WHISPER_MODEL.name)
        ttk.Combobox(row, textvariable=self.whisper_choice, values=_model_choices(), width=32, state="readonly").pack(side="left")
        ttk.Button(row, text="Save", command=self.save_whisper).pack(side="left", padx=8)
        self.whisper_note = ttk.Label(tab, text="", style="Muted.TLabel", wraplength=860, justify="left")
        self.whisper_note.pack(anchor="w")

        ttk.Label(tab, text="Plugin options", style="Heading.TLabel").pack(anchor="w", pady=(16, 4))
        self.cache_var = tk.BooleanVar(value=config.flag("model_cache"))
        self.turbo_var = tk.BooleanVar(value=config.flag("turbo"))
        ttk.Checkbutton(
            tab, text="Cache compiled models on disk", variable=self.cache_var,
            command=lambda: self.save_flag("model_cache", self.cache_var),
        ).pack(anchor="w")
        ttk.Label(
            tab,
            text=(
                "Saves about 0.1s of load time for roughly 1.2 GB, because the driver already "
                "caches the same graphs. Worth it only to avoid an occasional cold recompile."
            ),
            style="Muted.TLabel", wraplength=860, justify="left",
        ).pack(anchor="w", padx=(22, 0))
        ttk.Checkbutton(
            tab, text="NPU turbo", variable=self.turbo_var,
            command=lambda: self.save_flag("turbo", self.turbo_var),
        ).pack(anchor="w", pady=(8, 0))
        ttk.Label(
            tab,
            text="Measured no effect on these models (241.2ms against 240.1ms). Raises power draw.",
            style="Muted.TLabel", wraplength=860, justify="left",
        ).pack(anchor="w", padx=(22, 0))

        self.override_note = ttk.Label(tab, text="", style="Warn.TLabel", wraplength=860, justify="left")
        self.override_note.pack(anchor="w", pady=(14, 0))
        ttk.Label(tab, text=f"Settings file: {config.settings_path()}", style="Muted.TLabel").pack(anchor="w", pady=(12, 0))
        ttk.Label(
            tab,
            text="Changes apply to applications started afterwards, not to this window's loaded model.",
            style="Muted.TLabel",
        ).pack(anchor="w")
        self._refresh_overrides()

    def save_whisper(self):
        config.update("whisper_model", self.whisper_choice.get())
        self.whisper_note.configure(
            text=f"Saved. New transcriptions use {self.whisper_choice.get()} once an application is restarted."
        )
        self._refresh_overrides()

    def save_flag(self, name: str, variable: tk.BooleanVar):
        config.update(name, bool(variable.get()))
        self.status.set(f"Saved {name} = {variable.get()}")
        self._refresh_overrides()

    def _refresh_overrides(self):
        masked = [
            f"{name} (set by {config.overridden(name)})"
            for name in ("whisper_model", "model_cache", "turbo")
            if config.overridden(name)
        ]
        self.override_note.configure(
            text=(
                "These settings are currently overridden by environment variables, so changes here "
                "will not take effect until the variables are unset: " + ", ".join(masked)
            )
            if masked
            else ""
        )

    # ----------------------------------------------------------------- status

    def _status_tab(self):
        tab = self._tab("Status")
        row = ttk.Frame(tab)
        row.pack(fill="x")
        ttk.Button(row, text="Refresh", command=self.refresh_status).pack(side="left")
        ttk.Button(row, text="Copy", command=lambda: self._copy(self.status_out.get("1.0", "end").strip())).pack(side="left", padx=8)
        self.status_out = self._text(tab, height=18)
        self.refresh_status()

    def refresh_status(self):
        def work():
            # Reported as text rather than raised. This runs when the window
            # opens, and a machine with no working OpenVINO would otherwise be
            # greeted by a modal error before it could see anything else — on
            # the one tab whose entire job is to describe the situation.
            try:
                import openvino as ov
            except Exception as exc:
                return None, {}, f"unavailable ({exc})"

            core = ov.Core()
            devices = {name: core.get_property(name, "FULL_DEVICE_NAME") for name in core.available_devices}
            npu = {}
            if "NPU" in core.available_devices:
                for label, prop in (
                    ("architecture", "DEVICE_ARCHITECTURE"),
                    ("driver", "NPU_DRIVER_VERSION"),
                    ("compiler", "NPU_COMPILER_VERSION"),
                    ("precisions", "OPTIMIZATION_CAPABILITIES"),
                ):
                    try:
                        npu[label] = str(core.get_property("NPU", prop))
                    except Exception:
                        npu[label] = "unavailable"
            return devices, npu, ov.__version__

        def done(payload):
            devices, npu, version = payload
            lines = [f"OpenVINO {version}", ""]
            if devices is None:
                lines.append("No OpenVINO devices could be listed. Check the driver with intel-npu-info.")
                devices = {}
            lines += [f"{name:5s} {full}" for name, full in devices.items()]
            if npu:
                lines += [""] + [f"NPU {label:12s} {value}" for label, value in npu.items()]
            lines += ["", "Models"]
            for label, path in (
                ("speech", WHISPER_MODEL),
                ("embedding", EMBEDDING_MODEL),
                ("reranker", RERANK_MODEL),
                ("ocr", OCR_MODEL_DIR),
            ):
                lines.append(f"  {label:10s} {'present' if path.exists() else 'missing ':8s} {path}")
            desktop = summary()
            lines += [
                "",
                "Desktop",
                f"  session    {desktop['desktop']} ({desktop['session']})",
                f"  screenshot {', '.join(desktop['capture']) or 'NONE — install spectacle, gnome-screenshot, cosmic-screenshot, or grim'}",
                f"  clipboard  {', '.join(desktop['clipboard']) or 'NONE — install wl-clipboard, xclip, or xsel'}",
                "",
                "Paths",
                f"  data      {DATA_DIR}",
                f"  index     {SEMANTIC_DB} ({'present' if SEMANTIC_DB.exists() else 'not created yet'})",
                f"  settings  {config.settings_path()}",
            ]
            self._show(self.status_out, "\n".join(lines))

        self._run("Querying OpenVINO", work, done)

    # ------------------------------------------------------------------ close

    def close(self):
        if self.recorder:
            os.killpg(self.recorder.pid, signal.SIGTERM)
            self.recorder = None
        self._discard_recording()
        self.root.destroy()


def main():
    root = tk.Tk()
    Panel(root)
    root.mainloop()
