import os
import signal
import subprocess
import tempfile
import threading
from datetime import datetime
import tkinter as tk
from tkinter import messagebox, ttk

from .audio import decode_audio, pipeline, transcribe
from .desktop import copy_text
from .paths import HISTORY_FILE


class SpeechApp:
    def __init__(self, root):
        self.root, self.recorder, self.audio_path = root, None, None
        root.title("Intel NPU Speech to Text")
        root.geometry("720x470")
        root.configure(bg="#181a1f")
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TFrame", background="#181a1f")
        style.configure("TLabel", background="#181a1f", foreground="#eef1f6")
        style.configure("Title.TLabel", font=("Sans", 18, "bold"))
        style.configure("TButton", padding=9)
        frame = ttk.Frame(root, padding=20)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Intel NPU Speech to Text", style="Title.TLabel").pack(anchor="w")
        ttk.Label(frame, text="Private multilingual Whisper transcription on Intel AI Boost").pack(anchor="w", pady=(4, 14))
        controls = ttk.Frame(frame)
        controls.pack(fill="x")
        self.button = ttk.Button(controls, text="Loading NPU model…", state="disabled", command=self.toggle)
        self.button.pack(side="left")
        ttk.Button(controls, text="Copy", command=self.copy).pack(side="left", padx=8)
        self.status = tk.StringVar(value="Loading…")
        ttk.Label(frame, textvariable=self.status).pack(anchor="w", pady=10)
        self.text = tk.Text(frame, wrap="word", font=("Sans", 13), bg="#22252b", fg="#f4f6fa", insertbackground="white", relief="flat")
        self.text.pack(fill="both", expand=True)
        root.protocol("WM_DELETE_WINDOW", self.close)
        threading.Thread(target=self.load, daemon=True).start()

    def later(self, callback):
        self.root.after(0, callback)

    def load(self):
        try:
            pipeline()
            self.later(lambda: (self.status.set("Ready — using the system default microphone"), self.button.configure(text="Start recording", state="normal")))
        except Exception as exc:
            message = str(exc)
            self.later(lambda: messagebox.showerror("NPU model error", message))

    def toggle(self):
        if self.recorder is None:
            handle = tempfile.NamedTemporaryFile(prefix="intel-npu-speech-", suffix=".wav", delete=False)
            handle.close()
            self.audio_path = handle.name
            self.recorder = subprocess.Popen(
                ["pw-record", "--rate", "16000", "--channels", "1", "--format", "s16", self.audio_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            self.button.configure(text="Stop and transcribe")
            self.status.set("Recording…")
            return
        recorder, self.recorder = self.recorder, None
        os.killpg(recorder.pid, signal.SIGINT)
        recorder.wait(timeout=5)
        self.button.configure(text="Start recording", state="disabled")
        self.status.set("Transcribing on Intel AI Boost…")
        threading.Thread(target=self.finish, daemon=True).start()

    def finish(self):
        try:
            result = transcribe(decode_audio(self.audio_path))
            HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
            with HISTORY_FILE.open("a", encoding="utf-8") as history:
                history.write(f"\n[{datetime.now().isoformat(timespec='seconds')}]\n{result}\n")
            copy_text(result)
            def update():
                self.text.delete("1.0", "end")
                self.text.insert("1.0", result)
                self.status.set("Done — copied to the clipboard")
                self.button.configure(state="normal")
            self.later(update)
        except Exception as exc:
            message = str(exc)
            self.later(lambda: (messagebox.showerror("Transcription failed", message), self.button.configure(state="normal")))
        finally:
            self.discard_recording()

    def copy(self):
        copy_text(self.text.get("1.0", "end").strip())

    def close(self):
        if self.recorder:
            os.killpg(self.recorder.pid, signal.SIGTERM)
            self.recorder = None
        self.discard_recording()
        self.root.destroy()

    def discard_recording(self):
        """Remove the temporary recording so closing mid-capture leaves nothing behind."""
        if not self.audio_path:
            return
        try:
            os.unlink(self.audio_path)
        except OSError:
            pass
        self.audio_path = None


def main():
    root = tk.Tk()
    SpeechApp(root)
    root.mainloop()
