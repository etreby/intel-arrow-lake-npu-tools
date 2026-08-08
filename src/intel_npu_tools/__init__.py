"""Local Intel Arrow Lake NPU utilities."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("intel-arrow-lake-npu-tools")
except PackageNotFoundError:  # running from a source checkout without an install
    __version__ = "0.0.0+unknown"
