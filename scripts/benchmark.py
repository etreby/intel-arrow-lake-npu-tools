#!/usr/bin/env python3
"""Measure NPU model load and inference times, repeatably.

The performance numbers in this project's documentation were measured by hand.
This script exists so they can be re-checked after a driver, firmware, or
OpenVINO upgrade instead of being trusted indefinitely, and so a change that
claims a speedup can show one.

Each measurement runs in a fresh subprocess, because compilation happens once
per process: every model loader in this toolkit caches its compiled model in a
module-level singleton, so timing a second load in the same process would
measure a dictionary lookup. Warm latency is reported as a median rather than a
mean, so one scheduler hiccup does not move the number.

Models are exercised through the same entry points the applications use, rather
than through a private copy of their configuration, so the script cannot drift
away from what it claims to measure. The regimes are therefore driven by the
same environment variables a user would set.

There is deliberately no true cold-compile regime. Reaching one means clearing
the Level Zero driver's own blob cache in ~/.cache/ze_intel_npu_cache, which
costs the user a very slow next session on every model they own, and this script
has no business doing that to a machine it was merely asked to measure. The
first run against a fresh cache directory is the closest honest equivalent and
is reported as the `cache` regime's load time.

Read the load column with suspicion. That driver cache is shared and evictable,
so whether a given load pays a full recompile is not under this script's
control: the same Whisper model measured 4.69 seconds on one run and 0.50 on the
next, with nothing changed. A single load figure is close to meaningless, and
a difference between two regimes is only real if it survives re-running them.
The warm column does not have this problem, because compilation is already done
by the time it is sampled.
"""

import argparse
import json
import os
import platform
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path


TARGETS = ("embedding", "whisper", "ocr", "rerank")

# Each regime is exactly the environment a user would set, so the numbers
# describe configurations that can actually be shipped.
REGIMES = {
    "default": {},
    "cache": {"INTEL_NPU_TOOLS_MODEL_CACHE": "1"},
    "turbo": {"INTEL_NPU_TOOLS_TURBO": "1"},
}

SAMPLE_TEXT = ("the quick brown fox jumps over the lazy dog. " * 27)[:1200]
SAMPLE_QUERY = "how is authentication configured"
SAMPLE_PASSAGE = "the login handler validates JWT tokens before creating a session"


def _sample_audio():
    """Three seconds of 16 kHz tone plus noise, deterministic across runs."""
    import numpy as np

    rng = np.random.default_rng(0)
    t = np.linspace(0, 3, 16000 * 3, endpoint=False, dtype=np.float32)
    return (0.2 * np.sin(2 * np.pi * 220 * t) + 0.01 * rng.standard_normal(t.size)).astype("float32")


def _sample_image():
    import cv2
    import numpy as np

    image = np.full((400, 900, 3), 255, np.uint8)
    for row, line in enumerate(["intel npu tools", "semantic search 2026", "hello world"]):
        cv2.putText(image, line, (20, 80 + row * 100), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (0, 0, 0), 3)
    return image


def _load_embedding():
    from intel_npu_tools.semantic import embedding_pipeline

    pipe = embedding_pipeline()
    return lambda: pipe.embed_documents([SAMPLE_TEXT])


def _load_whisper():
    from intel_npu_tools.audio import pipeline

    pipe = pipeline()
    audio = _sample_audio()
    return lambda: pipe.generate(audio)


def _load_ocr():
    from intel_npu_tools.ocr import _run_ocr, ocr_models

    detector, recognizer = ocr_models()
    image = _sample_image()
    return lambda: _run_ocr(image, detector, recognizer)


def _load_rerank():
    from intel_npu_tools.rerank import rerank_pipeline

    reranker = rerank_pipeline()
    # One pair, so the warm number reads directly as milliseconds per pair.
    return lambda: reranker.rerank(SAMPLE_QUERY, [SAMPLE_PASSAGE])


LOADERS = {
    "embedding": _load_embedding,
    "whisper": _load_whisper,
    "ocr": _load_ocr,
    "rerank": _load_rerank,
}


def model_paths() -> dict:
    from intel_npu_tools.paths import EMBEDDING_MODEL, OCR_MODEL_DIR, RERANK_MODEL, WHISPER_MODEL

    return {
        "embedding": EMBEDDING_MODEL,
        "whisper": WHISPER_MODEL,
        "ocr": OCR_MODEL_DIR,
        "rerank": RERANK_MODEL,
    }


def run_worker(target: str, iterations: int) -> None:
    """Measure one target in this process and print the result as JSON."""
    started = time.perf_counter()
    warm = LOADERS[target]()
    load_seconds = time.perf_counter() - started

    warm()  # discard the first inference, which pays lazy allocation
    samples = []
    for _ in range(iterations):
        tick = time.perf_counter()
        warm()
        samples.append((time.perf_counter() - tick) * 1000)

    json.dump(
        {
            "target": target,
            "load_seconds": round(load_seconds, 3),
            "warm_ms_median": round(statistics.median(samples), 1),
            "warm_ms_min": round(min(samples), 1),
            "iterations": iterations,
        },
        sys.stdout,
    )


def describe_environment() -> dict:
    """Provenance, so a number in a pull request can be attributed to a machine."""
    import openvino as ov
    import openvino_genai

    core = ov.Core()
    facts = {
        "openvino": ov.__version__,
        "openvino_genai": getattr(openvino_genai, "__version__", "unknown"),
        "kernel": platform.release(),
        "python": platform.python_version(),
    }
    if "NPU" in core.available_devices:
        for label, prop in (
            ("npu", "FULL_DEVICE_NAME"),
            ("npu_architecture", "DEVICE_ARCHITECTURE"),
            ("npu_driver", "NPU_DRIVER_VERSION"),
            ("npu_compiler", "NPU_COMPILER_VERSION"),
        ):
            try:
                facts[label] = str(core.get_property("NPU", prop))
            except Exception:
                facts[label] = "unavailable"
    else:
        facts["npu"] = "not available"
    try:
        for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("model name"):
                facts["host_cpu"] = line.split(":", 1)[1].strip()
                break
    except OSError:
        pass
    return facts


def staged_home(stage: Path) -> Path:
    """A throwaway data directory whose models point at the real ones.

    Relocating INTEL_NPU_TOOLS_HOME is what keeps the `cache` regime from
    writing more than a gigabyte of compiled blobs into the user's own data
    directory just because they asked for a measurement. The models themselves
    are symlinked rather than copied, so nothing is duplicated on disk.
    """
    from intel_npu_tools.paths import MODEL_DIR

    models = stage / "models"
    models.mkdir(parents=True, exist_ok=True)
    if MODEL_DIR.is_dir():
        for entry in MODEL_DIR.iterdir():
            link = models / entry.name
            if not link.exists():
                link.symlink_to(entry.resolve(), target_is_directory=entry.is_dir())
    return stage


def measure(target: str, regime: str, iterations: int, home: Path, repeat_for_cache: bool) -> dict:
    environment = {
        **os.environ,
        **REGIMES[regime],
        "INTEL_NPU_TOOLS_HOME": str(home),
        "PYTHONPATH": os.environ.get("PYTHONPATH", str(Path(__file__).resolve().parent.parent / "src")),
    }
    for name in ("INTEL_NPU_TOOLS_MODEL_CACHE", "INTEL_NPU_TOOLS_TURBO"):
        if name not in REGIMES[regime]:
            environment.pop(name, None)

    command = [sys.executable, str(Path(__file__).resolve()), "--worker", target, "--iterations", str(iterations)]

    def once() -> subprocess.CompletedProcess:
        return subprocess.run(command, env=environment, capture_output=True, text=True)

    if repeat_for_cache:
        # The first run writes the blob; the measured run reads it. Without this
        # the `cache` regime would report the cost of populating the cache and
        # call it the benefit of having one.
        once()
    result = once()
    if result.returncode != 0:
        tail = (result.stderr or "").strip().splitlines()
        return {"target": target, "regime": regime, "error": tail[-1] if tail else "failed"}
    return {"target": target, "regime": regime, **json.loads(result.stdout)}


def render(rows: list[dict], facts: dict) -> str:
    lines = [
        f"openvino {facts.get('openvino', '?')}  genai {facts.get('openvino_genai', '?')}",
        f"NPU: {facts.get('npu', '?')}  driver {facts.get('npu_driver', '?')}  "
        f"compiler {facts.get('npu_compiler', '?')}  arch {facts.get('npu_architecture', '?')}",
        f"host: {facts.get('host_cpu', '?')}  kernel {facts.get('kernel', '?')}  "
        f"python {facts.get('python', '?')}",
        "",
        f"{'target':<11}{'regime':<10}{'load(s)':>9}{'warm(ms)':>10}{'min(ms)':>9}",
    ]
    for row in rows:
        if "error" in row:
            lines.append(f"{row['target']:<11}{row['regime']:<10}{'—':>9}{'—':>10}{'—':>9}")
            # On its own line, because the reason is usually a path and
            # truncating it to fit a column hides the part that identifies it.
            lines.append(f"{'':<11}{row['error']}")
        else:
            lines.append(
                f"{row['target']:<11}{row['regime']:<10}{row['load_seconds']:>9.2f}"
                f"{row['warm_ms_median']:>10.1f}{row['warm_ms_min']:>9.1f}"
            )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--targets", default=",".join(TARGETS), help=f"comma-separated: {', '.join(TARGETS)}")
    parser.add_argument("--regimes", default="default", help=f"comma-separated: {', '.join(REGIMES)}")
    parser.add_argument("--iterations", type=int, default=5, help="warm inferences per measurement")
    parser.add_argument("--json", action="store_true", help="emit JSON for pasting into a pull request")
    parser.add_argument("--worker", choices=TARGETS, help=argparse.SUPPRESS)
    arguments = parser.parse_args()

    if arguments.worker:
        run_worker(arguments.worker, arguments.iterations)
        return 0

    targets = [item.strip() for item in arguments.targets.split(",") if item.strip()]
    regimes = [item.strip() for item in arguments.regimes.split(",") if item.strip()]
    for name, allowed in (("target", targets), ("regime", regimes)):
        unknown = set(allowed) - set(TARGETS if name == "target" else REGIMES)
        if unknown:
            parser.error(f"unknown {name}: {', '.join(sorted(unknown))}")

    facts = describe_environment()
    available = model_paths()
    rows = []
    with tempfile.TemporaryDirectory(prefix="intel-npu-benchmark-") as stage:
        home = staged_home(Path(stage))
        for target in targets:
            if not available[target].exists():
                rows.append({"target": target, "regime": "—", "error": f"model not installed at {available[target]}"})
                continue
            for regime in regimes:
                rows.append(
                    measure(target, regime, arguments.iterations, home, repeat_for_cache=(regime == "cache"))
                )

    if arguments.json:
        json.dump({"environment": facts, "results": rows}, sys.stdout, indent=2)
        print()
    else:
        print(render(rows, facts))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
