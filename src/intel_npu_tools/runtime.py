"""Shared OpenVINO plugin properties for every NPU model this toolkit compiles.

Deliberately free of OpenVINO imports so that this module, and everything that
imports it, still loads on a machine without OpenVINO installed. The continuous
integration workflow asserts exactly that, because the heavy inference imports
are what make the package slow to load and impossible to test without hardware.
"""

import os

from .paths import MODEL_CACHE_DIR


TURBO_ENV = "INTEL_NPU_TOOLS_TURBO"
MODEL_CACHE_ENV = "INTEL_NPU_TOOLS_MODEL_CACHE"
_TRUTHY = {"1", "true", "yes", "on"}


def _flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in _TRUTHY


def turbo_enabled() -> bool:
    return _flag(TURBO_ENV)


def model_cache_enabled() -> bool:
    return _flag(MODEL_CACHE_ENV)


def npu_properties(**overrides) -> dict:
    """Plugin properties for compiling a model on the NPU.

    ``NPU_COMPILER_TYPE=DRIVER`` matches the Intel Ubuntu packages this project
    installs, and is the setting the semantic pipeline has always used.

    ``CACHE_DIR`` is off unless ``INTEL_NPU_TOOLS_MODEL_CACHE`` is set. The Level
    Zero driver already keeps its own compiled blobs under
    ``~/.cache/ze_intel_npu_cache``, so an OpenVINO cache duplicates them rather
    than replacing them, and while that driver cache is warm it saves very
    little: measured with ``scripts/benchmark.py``, embedding load went from
    0.98 to 0.89 seconds and Whisper from 0.50 to 0.79, which is noise.

    Its real value is variance, not the warm floor. The driver's cache is shared
    and evictable, so a model occasionally has to be recompiled from scratch,
    and that is expensive: the same Whisper load measured 4.69 seconds on a run
    that hit a cold compile, against 0.50 seconds warm. A cache under the
    toolkit's own data directory is never evicted by anything else, so enabling
    this trades disk for never paying that stall again. The disk is not small —
    roughly 340 MB for Whisper and 1.2 GB for the embedding model, plus a
    one-off 10.4 second first run to write the larger blob — which is why it is
    a switch and not a default.

    ``NPU_TURBO`` raises the NPU clock and therefore power draw, so it stays off
    unless ``INTEL_NPU_TOOLS_TURBO`` is set. On this hardware it changed nothing
    measurable: embedding latency was 240.1 ms with it off and 241.2 ms with it
    on, and the compiled model was confirmed to report ``NPU_TURBO`` as ``True``,
    so that is a real result rather than a property the plugin ignored. It stays
    available because the effect is workload-dependent and costs nothing to
    offer, but do not expect it to buy anything for the models shipped here.

    Environment variables rather than constants keep both switchable for
    ``scripts/benchmark.py`` without editing installed code.
    """
    properties = {"NPU_COMPILER_TYPE": "DRIVER"}
    if model_cache_enabled():
        MODEL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        properties["CACHE_DIR"] = str(MODEL_CACHE_DIR)
    if turbo_enabled():
        properties["NPU_TURBO"] = True
    properties.update(overrides)
    return properties
