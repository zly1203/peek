"""Unit tests for MCP tools: screenshot and get_latest_capture."""

import json
import base64
from unittest.mock import AsyncMock, patch, MagicMock
import pytest

from src.mcp_server import screenshot, get_latest_capture, CAPTURES_DIR


@pytest.mark.asyncio
async def test_get_latest_capture_no_files(tmp_captures, monkeypatch):
    """Returns 'no captures' message when no files exist."""
    monkeypatch.setattr("src.mcp_server.CAPTURES_DIR", tmp_captures)

    result = await get_latest_capture()

    assert len(result) == 1
    assert result[0].type == "text"
    assert "No captures yet" in result[0].text


@pytest.mark.asyncio
async def test_get_latest_capture_with_screenshot(sample_capture, monkeypatch):
    """Returns JSON metadata + screenshot image."""
    captures, metadata, png_bytes = sample_capture
    monkeypatch.setattr("src.mcp_server.CAPTURES_DIR", captures)

    result = await get_latest_capture()

    # Should have 2 items: TextContent (JSON) + ImageContent (screenshot)
    assert len(result) == 2
    assert result[0].type == "text"
    returned_metadata = json.loads(result[0].text)
    assert returned_metadata["mode"] == "region"
    assert returned_metadata["url"] == "http://localhost:3000"

    assert result[1].type == "image"
    assert result[1].mimeType == "image/png"
    assert base64.b64decode(result[1].data) == png_bytes


@pytest.mark.asyncio
async def test_get_latest_capture_with_annotation(sample_annotated_capture, monkeypatch):
    """Returns JSON + screenshot + annotation overlay."""
    captures, metadata, png_bytes = sample_annotated_capture
    monkeypatch.setattr("src.mcp_server.CAPTURES_DIR", captures)

    result = await get_latest_capture()

    # Should have 3 items: TextContent + ImageContent (screenshot) + ImageContent (annotation)
    assert len(result) == 3
    assert result[0].type == "text"
    assert result[1].type == "image"
    assert result[2].type == "image"

    # Verify annotation overlay is present
    returned_metadata = json.loads(result[0].text)
    assert returned_metadata["annotationOverlay"] == "capture_latest_annot.png"


@pytest.mark.asyncio
async def test_get_latest_capture_no_annotation_file(sample_capture, monkeypatch):
    """Does not include annotation when file doesn't exist."""
    captures, metadata, png_bytes = sample_capture
    # Metadata has no annotationOverlay key (region mode)
    monkeypatch.setattr("src.mcp_server.CAPTURES_DIR", captures)

    result = await get_latest_capture()

    # Only JSON + screenshot, no annotation
    assert len(result) == 2


@pytest.mark.asyncio
async def test_screenshot_tool_success(monkeypatch):
    """screenshot tool returns ImageContent on success."""
    fake_png = b"fake_screenshot_data"

    async def mock_ensure():
        return MagicMock()

    async def mock_take_screenshot(browser, url, **kwargs):
        return fake_png

    monkeypatch.setattr("src.mcp_server._ensure_browser", mock_ensure)
    monkeypatch.setattr("src.mcp_server.take_screenshot", mock_take_screenshot)

    result = await screenshot(url="http://localhost:3000")

    assert len(result) == 1
    assert result[0].type == "image"
    assert result[0].mimeType == "image/png"
    assert base64.b64decode(result[0].data) == fake_png


@pytest.mark.asyncio
async def test_screenshot_tool_passes_params(monkeypatch):
    """screenshot tool forwards scroll_y, width, height."""
    captured_kwargs = {}

    async def mock_ensure():
        return MagicMock()

    async def mock_take_screenshot(browser, url, **kwargs):
        captured_kwargs.update(kwargs)
        return b"png"

    monkeypatch.setattr("src.mcp_server._ensure_browser", mock_ensure)
    monkeypatch.setattr("src.mcp_server.take_screenshot", mock_take_screenshot)

    await screenshot(url="http://localhost:3000", scroll_y=500, width=800, height=600)

    assert captured_kwargs["scroll_y"] == 500
    assert captured_kwargs["width"] == 800
    assert captured_kwargs["height"] == 600


@pytest.mark.asyncio
async def test_screenshot_tool_error(monkeypatch):
    """screenshot tool returns TextContent on error."""
    async def mock_ensure():
        raise ConnectionError("Browser crashed")

    monkeypatch.setattr("src.mcp_server._ensure_browser", mock_ensure)

    result = await screenshot(url="http://localhost:3000")

    assert len(result) == 1
    assert result[0].type == "text"
    assert "Screenshot failed" in result[0].text
    assert "Browser crashed" in result[0].text
