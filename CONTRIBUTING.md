# Contributing

Contributions are welcome. Useful areas include additional Intel NPU generations, GNOME/wlroots screenshot support, better OCR models, packaging for more distributions, accessibility improvements, translations, and repeatable hardware benchmarks.

## Before opening a pull request

1. Search existing issues and pull requests.
2. Open an issue before large architectural changes.
3. Keep hardware-specific behavior explicit and fail safely on untested devices.
4. Do not commit model weights, driver packages, recordings, screenshots, credentials, or personal paths.
5. Preserve local-only processing unless a network feature is clearly disclosed and opt-in.

## Development setup

```bash
git clone https://github.com/etreby/intel-arrow-lake-npu-tools.git
cd intel-arrow-lake-npu-tools
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
python -m compileall -q src tests
bash -n install.sh uninstall.sh scripts/*.sh
```

NPU runtime tests require compatible hardware. If you cannot test on an NPU, say so clearly in the pull request.

If a change claims a performance effect, show it with `scripts/benchmark.py` and paste the table, which carries a header naming the driver, compiler, and OpenVINO versions it ran against. Re-run any load-time difference before reporting it: the driver's compiled-blob cache is shared and evictable, so a single load measurement can be a cold compile rather than the effect you are describing.

## Pull requests

- Explain what changed and why.
- List the CPU/NPU, distribution, kernel, driver, and OpenVINO versions used.
- Include exact validation commands and results.
- Update documentation when user-visible behavior changes.
- Keep unrelated formatting or refactoring out of focused fixes.

By contributing, you agree that your contribution is licensed under the repository's MIT License.
