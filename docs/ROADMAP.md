# Roadmap

This file records what is worth building on Intel NPU 3720 and, just as importantly, what is not. Every entry names the evidence behind it. Where a measurement contradicted an expectation, the measurement is kept and the expectation is written down beside it, so the same idea is not proposed again next year.

## What the silicon is

The NPU reports 13.1 TOPS on INT8 and 6.55 TFLOPS on FP16, and **zero** on FP32 and BF16. A model that is not quantised to INT8 or FP16 does not run slowly here; it silently falls back to the CPU and stops being an NPU workload at all. `OPTIMIZATION_CAPABILITIES` is `FP16, INT8, EXPORT_IMPORT`. Static shapes are required, and `NPU_DEVICE_TOTAL_MEM_SIZE` reports shared system memory rather than dedicated memory.

Two measurements shape everything below, and both cut against the obvious pitch.

The NPU is **not faster than the host CPU** for the models shipped here. Embedding a 1200-character chunk takes 0.247 seconds on the NPU against 0.235 seconds on twenty-four CPU cores, and the CPU reaches 0.172 seconds once it batches, which the NPU cannot do — `TextEmbeddingPipeline` fails to compile with `batch_size` above one. The reason to use the NPU is therefore not speed. It is that the work leaves the CPU entirely, so an agent's builds and tests keep every core, and that the tokens produced never enter a language model's context window.

Compiled-model caching is **not** the free win it appears to be, and measuring it is a good illustration of how easily this hardware misleads. The Level Zero driver already keeps its own compiled blobs, so an OpenVINO `CACHE_DIR` duplicates rather than replaces them. While that driver cache is warm, enabling it changes almost nothing: embedding load moved from 0.98 to 0.89 seconds and Whisper from 0.50 to 0.79.

A single run appeared to show otherwise — Whisper loading in 4.69 seconds without the cache against 0.75 with it, an apparent six-fold win. Re-running showed 0.50 seconds without it. The 4.69 seconds was a cold compile that happened to fall in the uncached column, not a cost the cache was avoiding. **Load times on this device depend on the driver cache's state, so any single measurement of one is untrustworthy**; this is exactly what `scripts/benchmark.py` exists to make cheap to re-check.

The honest case for caching is therefore variance rather than the warm floor. The driver's cache is shared and evictable, so a model does occasionally face that 4.69-second recompile, while a cache under the toolkit's own data directory is never evicted by anything else. The cost is roughly 340 MB for Whisper and 1.2 GB for the embedding model, plus a one-off 10.4-second first run to write the larger blob. It is available behind `INTEL_NPU_TOOLS_MODEL_CACHE` and off by default. That 10.4-second figure is worth noting for a second reason: it is almost exactly the "approximately 10.7 seconds" this project's semantic-search guide has always quoted, which suggests that number described a cold compile and never described steady state.

`NPU_TURBO` changed nothing measurable: 240.1 milliseconds against 241.2. The compiled model was confirmed to report the property as enabled, so that is a real result and not a setting the plugin ignored.

## Done

**Compile once per process.** The OCR path used to construct an OpenVINO core and compile both of its models on every call, so a single screenshot paid full driver compilation twice before a pixel was read. It now uses the lazy singleton that the speech and embedding paths already used, which made repeat calls 4.9 times faster, from 0.176 seconds to 0.036.

**`context_filter`.** Returns only the parts of a large text file relevant to a question, copied verbatim with line numbers. On a 100 KB build log it returned four spans in place of 2,547 lines — an estimated 95 percent reduction, from roughly 25,000 tokens to 1,200 — and found a linker failure buried at line 1,400. It reuses the embedding model that is already installed, so it needs no new download. See the semantic-search guide for its limits.

**Cross-encoder reranking**, opt-in per query. See below for why it is not on by default.

**A larger Whisper, as an option rather than a default.** `whisper-small-int8-ov` compiles on the NPU and is selectable through `INTEL_NPU_TOOLS_WHISPER_MODEL`. It is a trade, not an upgrade. Measured over eight recorded clips mixed with noise at known signal-to-noise ratios: identical to base on clean audio (8/8 each) and identical when the noise overwhelms the speech (2/8 each at 0 dB), but clearly better in between — 8/8 against 6/8 at 10 dB and 6/8 against 5/8 at 5 dB. It costs 2.6 times the latency, 237 milliseconds per clip against 90, and three times the download at 246 MB. Base remains the default because dictation in a quiet room is the common case and is where base loses nothing.

There is no `whisper-medium` worth adding: the OpenVINO conversions of medium are English-only, and this project's speech feature is multilingual.

**`screen_to_text`.** Renders a screenshot as structured text instead of an image: 33.7 times fewer tokens than the screenshot in `text` mode and 8.3 in the default `lines` mode, measured on a 1080p application window. Its reading order comes from Tesseract's page segmentation, which keeps a sidebar and an editor pane apart; the `(y // 30, x)` heuristic in `npu_ocr` returns them stitched into one line. It is labelled as a Tesseract tool because that is what it is — see the note on the recogniser below.

**`scripts/benchmark.py`.** Samples each model in a fresh subprocess, because every loader here caches its compiled model in a module-level singleton and a second load in the same process would measure a dictionary lookup. It reports median warm latency with a provenance header naming the driver, compiler, and OpenVINO versions, so a number in a pull request can be attributed to a machine. It has already paid for itself once, by catching the cold-compile artefact described above.

## Blocked, with the specific reason

**Silero voice activity detection does not convert to OpenVINO at all.** This is not an NPU limitation; the model never reaches the device. `read_model` fails in the ONNX frontend with `Conversion is failed for: Conv-16, ReduceMean-16`, because the graph contains an `If` node whose branches have dynamic rank, and the frontend needs a static rank to translate a convolution. Five exports were tried across three repositories — `onnx-community/silero-vad` at fp32, fp16, int8, and bnb4, plus `deepghs/silero-vad-onnx` and `mgonzs13/silero-vad-onnx` — and every one failed identically, which places the cause in the model architecture rather than in any particular export. Revisit if Silero publishes a static-rank export or if a future OpenVINO ONNX frontend handles dynamic-rank branches. Do not spend time on further quantisation variants; they share the graph.

**CLIP and SigLIP image embeddings have no usable starting point.** No OpenVINO IR conversion of either exists publicly: the OpenVINO organisation publishes none, and a broad search returns only unrelated multimodal checkpoints that happen to match the string. Converting one is possible in principle but not from here — it needs `torch`, `transformers`, and `optimum-intel`, none of which are installed, and adding them would put roughly 2.5 GB of build-time dependencies into a project whose runtime deliberately has no PyTorch. Doing it properly means a separate conversion step, run once by a maintainer, with the resulting IR published somewhere this project can download it, plus a licence review for redistribution. That is a piece of work in its own right, not a feature to slip into a release, and until it exists there is nothing to verify on the NPU.

## Not worth doing, and why

**Reranking by default.** A cross-encoder scores a query and a passage together and is in principle much better than embedding similarity at deciding which of several similar passages is the one being asked about. Measured on this repository it helped when it was confident and hurt when it was not. Asked how to write a skill, it promoted the right passage with a score of +4.95. Asked why the driver needs a specific PCI id, every score fell around -6.5 and it discarded the correct passage that plain cosine similarity had ranked first. The rule appears to be that a large positive score means the model recognised the answer, and that when nothing scores positively its ordering is noise. Reranking is therefore off unless `--rerank` is passed. A confidence floor, where the reranker may only promote passages scoring above some threshold, is the obvious refinement; six queries is too small a sample to choose that threshold, so it has not been chosen.

**A local language model for summarising.** `LLMPipeline` exists and a small quantised model would load. It is still the wrong tool here. Static shapes fix the context length at compile time, prompt processing is slow, and a generated summary cannot be cited. The verbatim guarantee is the whole reason `context_filter` is trustworthy, and a summariser trades it away for nothing this project needs.

**OCR as a replacement for a browser's accessibility tree.** Where a DOM exists, reading it is exact, includes content that is scrolled off screen, and costs no model tokens at all. No amount of image recognition improves on that. Screenshot text extraction earns its place only where there is no DOM: native desktop applications, remote desktop sessions, canvas and WebGL surfaces, video frames, scanned documents, and screenshots a person pasted.

## Next

**A better OCR model.** The bundled recogniser is a CTC model over a hardcoded 37-symbol alphabet of lowercase Latin letters and digits. It cannot emit capitals, punctuation, or any non-Latin script — "File → Save As…" becomes `filesaveas` — and this is a property of the model, not a setting. The codebase already concedes the point, because `extract_text` prefers Tesseract output whenever Tesseract returns anything, and `screen_to_text` uses Tesseract outright. Replacing the recogniser with a PaddleOCR conversion is the single change that would make screenshot work genuinely NPU-backed. Unknown: whether its variable-width axis can be frozen to a shape the NPU plugin accepts, and how it reads UI text at small sizes.

Accuracy is the reason this matters, not just principle. On a synthetic 1080p editor window Tesseract read `src` as `sre`, `context_filter.py` as `context_fitter.py`, and `mcp_server.py` as `mep_server.py`. The per-line confidence scores did flag the worst of them, dropping to 66 where the clean lines scored above 90, so a caller that checks confidence is not misled — but small antialiased interface text is where this transcription is weakest, and interface text is the whole point.

**Voice activity detection, if a convertible model appears.** See the blocked section below; Silero cannot currently be used. What a detector would buy is worth restating, because it is the clearest remaining fit for this hardware: continuous listening at very low power, turning speech transcription from a click-to-start interaction into an always-available one.

A classical detector would deliver most of that with no model at all. Frame energy and zero-crossing rate, computed in a few lines of NumPy, is enough to find speech boundaries in a stream, and `transcribe` already carries a crude version of it in the amplitude gate that returns "(No speech detected)". That path is open, it is cheap, and it should be labelled for what it is: a signal-processing feature that leaves the NPU idle, not the neural detector this entry originally described.

**`screen_to_text` and the OCR replacement above** are the only substantial pieces of this roadmap not yet built.
