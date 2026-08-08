"""Import coverage for the MCP entry point.

compileall only checks syntax, so without this the flagship `intel-npu-mcp`
command could ship with a broken import on a green build.
"""

import asyncio

import pytest

pytest.importorskip("mcp", reason="the MCP SDK is required to exercise the server module")

from intel_npu_tools import mcp_server  # noqa: E402


EXPECTED_TOOLS = {
    "npu_status",
    "transcribe_audio",
    "record_and_transcribe",
    "ocr_image",
    "ocr_current_monitor",
    "semantic_index",
    "semantic_search",
    "semantic_index_status",
    "open_speech_app",
    "open_ocr_selector",
}


def test_every_documented_tool_is_registered():
    tools = asyncio.run(mcp_server.mcp.list_tools())
    assert {tool.name for tool in tools} == EXPECTED_TOOLS


def test_every_tool_is_described_for_agents():
    tools = asyncio.run(mcp_server.mcp.list_tools())
    assert all(tool.description for tool in tools)


def test_local_file_rejects_unsupported_and_missing_paths(tmp_path):
    image = tmp_path / "shot.png"
    image.write_bytes(b"")
    assert mcp_server.local_file(str(image), (".png",)) == image.resolve()

    with pytest.raises(ValueError, match="Unsupported file type"):
        mcp_server.local_file(str(image), (".jpg",))
    with pytest.raises(ValueError, match="File does not exist"):
        mcp_server.local_file(str(tmp_path / "missing.png"), (".png",))
