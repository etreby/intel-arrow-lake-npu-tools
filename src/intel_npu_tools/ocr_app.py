import subprocess
import tempfile
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk

from .ocr import extract_text


def result_window(result: dict):
    root = tk.Tk()
    root.title("Intel NPU Screenshot OCR")
    root.geometry("760x500")
    root.configure(bg="#181a1f")
    style = ttk.Style()
    style.theme_use("clam")
    style.configure("TFrame", background="#181a1f")
    style.configure("TLabel", background="#181a1f", foreground="#eef1f6")
    frame = ttk.Frame(root, padding=20)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text=f"Intel NPU detected {result['npu_regions']} text region(s)").pack(anchor="w", pady=(0, 10))
    box = tk.Text(frame, wrap="word", font=("Sans", 13), bg="#22252b", fg="#f4f6fa", insertbackground="white")
    box.pack(fill="both", expand=True)
    box.insert("1.0", result["text"])
    ttk.Button(frame, text="Copy text", command=lambda: subprocess.run(["wl-copy", "--", box.get("1.0", "end").strip()])).pack(anchor="w", pady=(10, 0))
    root.mainloop()


def main():
    with tempfile.NamedTemporaryFile(prefix="intel-npu-ocr-", suffix=".png") as image:
        capture = subprocess.run(["spectacle", "--region", "--background", "--nonotify", "--output", image.name])
        if capture.returncode or not Path(image.name).stat().st_size:
            return
        try:
            result = extract_text(Path(image.name))
            subprocess.run(["wl-copy", "--", result["text"]], check=True)
            result_window(result)
        except Exception as exc:
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("OCR failed", str(exc))
