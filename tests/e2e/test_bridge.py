"""Layer A — Bridge server integration tests.

Tests the bridge server's HTTP endpoints with real Playwright screenshots.
Covers capture, screenshot, CORS, static file serving, and MCP tool integration.
"""

import base64
import time
from pathlib import Path

import httpx
import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.bridge]

# Minimal valid 1x1 red-ish PNG for annotate tests
TINY_PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00"
    b"\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00"
    b"\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _element_capture_payload(page_url: str) -> dict:
    """Build a minimal element-mode capture payload."""
    return {
        "mode": "element",
        "url": page_url,
        "element": {
            "tagName": "BUTTON",
            "className": "primary btn",
            "textContent": "Click me",
            "selector": "button.primary.btn",
        },
        "viewport": {"width": 1280, "height": 800},
        "scroll": {"x": 0, "y": 0},
    }


def _region_capture_payload(page_url: str) -> dict:
    """Build a minimal region-mode capture payload."""
    return {
        "mode": "region",
        "url": page_url,
        "region": {"x": 10, "y": 20, "width": 200, "height": 150},
        "viewport": {"width": 1280, "height": 800},
        "scroll": {"x": 0, "y": 0},
    }


def _annotate_capture_payload(page_url: str) -> dict:
    """Build a minimal annotate-mode capture payload with screenshot."""
    return {
        "mode": "annotate",
        "url": page_url,
        "annotationBounds": {"x": 0, "y": 0, "width": 100, "height": 100},
        "screenshotBase64": base64.b64encode(TINY_PNG_BYTES).decode(),
        "viewport": {"width": 1280, "height": 800},
        "scroll": {"x": 0, "y": 0},
    }


# ─── Core capture tests ───


@pytest.mark.asyncio
async def test_post_element_capture_and_get_latest(bridge_server, test_page_server):
    """POST element capture, GET latest returns it with correct metadata and PNG."""
    base_url, captures_dir = bridge_server
    payload = _element_capture_payload(test_page_server)

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{base_url}/api/capture", json=payload, timeout=30
        )
        assert resp.status_code == 200
        post_data = resp.json()
        assert post_data["status"] == "ok"
        assert "timestamp" in post_data

        resp = await client.get(f"{base_url}/api/capture/latest", timeout=30)
        assert resp.status_code == 200
        latest = resp.json()
        assert latest["mode"] == "element"
        assert latest["element"]["tagName"] == "BUTTON"
        assert latest["screenshot"] == "capture_latest.png"
        assert latest["url"] == test_page_server

    # Verify PNG file exists and starts with PNG magic bytes
    png_path = captures_dir / "capture_latest.png"
    assert png_path.exists()
    assert png_path.read_bytes()[:4] == b"\x89PNG"


@pytest.mark.asyncio
async def test_post_region_capture_and_get_latest(bridge_server, test_page_server):
    """POST region capture, verify region coordinates preserved."""
    base_url, captures_dir = bridge_server
    payload = _region_capture_payload(test_page_server)

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{base_url}/api/capture", json=payload, timeout=30
        )
        assert resp.status_code == 200

        resp = await client.get(f"{base_url}/api/capture/latest", timeout=30)
        assert resp.status_code == 200
        latest = resp.json()
        assert latest["mode"] == "region"
        assert latest["region"] == {"x": 10, "y": 20, "width": 200, "height": 150}
        assert latest["screenshot"] == "capture_latest.png"


@pytest.mark.asyncio
async def test_post_annotate_capture_and_get_latest(bridge_server, test_page_server):
    """POST annotate with base64 screenshot, verify annotation overlay saved."""
    base_url, captures_dir = bridge_server
    payload = _annotate_capture_payload(test_page_server)

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{base_url}/api/capture", json=payload, timeout=30
        )
        assert resp.status_code == 200

        resp = await client.get(f"{base_url}/api/capture/latest", timeout=30)
        assert resp.status_code == 200
        latest = resp.json()
        assert latest["mode"] == "annotate"
        assert latest["annotationOverlay"] == "capture_latest_annot.png"
        # screenshotBase64 should be stripped from saved JSON
        assert "screenshotBase64" not in latest

    # Verify annotation PNG saved correctly
    annot_path = captures_dir / "capture_latest_annot.png"
    assert annot_path.exists()
    assert annot_path.read_bytes() == TINY_PNG_BYTES


# ─── Screenshot endpoint tests ───


@pytest.mark.asyncio
async def test_screenshot_endpoint(bridge_server, test_page_server):
    """GET /api/screenshot returns valid PNG with correct content-type."""
    base_url, _ = bridge_server

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{base_url}/api/screenshot",
            params={"url": test_page_server},
            timeout=30,
        )
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/png"
        assert resp.content[:4] == b"\x89PNG"
        assert len(resp.content) > 100  # real screenshot should be non-trivial


@pytest.mark.asyncio
async def test_screenshot_endpoint_custom_params(bridge_server, test_page_server):
    """Different viewport params produce different screenshots."""
    base_url, _ = bridge_server

    async with httpx.AsyncClient() as client:
        resp1 = await client.get(
            f"{base_url}/api/screenshot",
            params={"url": test_page_server, "width": 800, "height": 600},
            timeout=30,
        )
        resp2 = await client.get(
            f"{base_url}/api/screenshot",
            params={"url": test_page_server, "width": 400, "height": 300},
            timeout=30,
        )

    assert resp1.status_code == 200
    assert resp2.status_code == 200
    # Different viewport sizes should produce different image bytes
    assert resp1.content != resp2.content


# ─── Ordering and file tests ───


@pytest.mark.asyncio
async def test_latest_returns_newest_capture(bridge_server, test_page_server):
    """POST twice (with 1s sleep between), GET latest returns the second."""
    base_url, _ = bridge_server
    payload1 = _element_capture_payload(test_page_server)
    payload2 = _region_capture_payload(test_page_server)

    async with httpx.AsyncClient() as client:
        resp1 = await client.post(
            f"{base_url}/api/capture", json=payload1, timeout=30
        )
        assert resp1.status_code == 200
        ts1 = resp1.json()["timestamp"]

        # Sleep to ensure different timestamp (format is YYYYMMDD_HHMMSS)
        time.sleep(1)

        resp2 = await client.post(
            f"{base_url}/api/capture", json=payload2, timeout=30
        )
        assert resp2.status_code == 200
        ts2 = resp2.json()["timestamp"]
        assert ts1 != ts2

        resp = await client.get(f"{base_url}/api/capture/latest", timeout=30)
        assert resp.status_code == 200
        latest = resp.json()
        assert latest["timestamp"] == ts2
        assert latest["mode"] == "region"


@pytest.mark.asyncio
async def test_timestamped_files_created(bridge_server, test_page_server):
    """After capture, both latest and timestamped files exist."""
    base_url, captures_dir = bridge_server
    payload = _element_capture_payload(test_page_server)

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{base_url}/api/capture", json=payload, timeout=30
        )
        assert resp.status_code == 200
        ts = resp.json()["timestamp"]

    # Latest files
    assert (captures_dir / "capture_latest.json").exists()
    assert (captures_dir / "capture_latest.png").exists()

    # Timestamped files
    assert (captures_dir / f"capture_{ts}.json").exists()
    assert (captures_dir / f"capture_{ts}.png").exists()


# ─── MCP tool integration ───


@pytest.mark.asyncio
async def test_mcp_screenshot_tool_integration(bridge_server, test_page_server):
    """Call actual MCP screenshot() function, verify ImageContent with PNG."""
    # The bridge_server fixture ensures PEEK_CAPTURES_DIR is set and modules are reloaded
    from src.mcp_server import screenshot

    result = await screenshot(url=test_page_server, width=1280, height=800)
    assert len(result) == 1

    img_content = result[0]
    assert img_content.type == "image"
    assert img_content.mimeType == "image/png"

    # Decode and verify it's a valid PNG
    png_bytes = base64.b64decode(img_content.data)
    assert png_bytes[:4] == b"\x89PNG"
    assert len(png_bytes) > 100


# ─── CORS tests ───


@pytest.mark.asyncio
async def test_cors_localhost_origin_allowed(bridge_server):
    """OPTIONS with localhost Origin gets CORS headers."""
    base_url, _ = bridge_server

    async with httpx.AsyncClient() as client:
        resp = await client.options(
            f"{base_url}/api/capture",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
            timeout=30,
        )
    assert resp.status_code == 200
    assert "access-control-allow-origin" in resp.headers
    assert resp.headers["access-control-allow-origin"] == "http://localhost:3000"


@pytest.mark.asyncio
async def test_cors_external_origin_rejected(bridge_server):
    """OPTIONS with evil.com Origin does NOT get CORS headers."""
    base_url, _ = bridge_server

    async with httpx.AsyncClient() as client:
        resp = await client.options(
            f"{base_url}/api/capture",
            headers={
                "Origin": "https://evil.com",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
            timeout=30,
        )
    # Should not get CORS allow-origin header for external origin
    assert resp.headers.get("access-control-allow-origin") != "https://evil.com"


# ─── Static file tests ───


@pytest.mark.asyncio
async def test_setup_page(bridge_server):
    """GET / returns HTML with 'Peek' and bookmarklet."""
    base_url, _ = bridge_server

    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{base_url}/", timeout=30)
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    body = resp.text
    assert "Peek" in body
    assert "bookmarklet" in body.lower() or "Peek" in body


@pytest.mark.asyncio
async def test_static_inspector_js(bridge_server):
    """GET /static/inspector.js returns JS."""
    base_url, _ = bridge_server

    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{base_url}/static/inspector.js", timeout=30)
    assert resp.status_code == 200
    content_type = resp.headers["content-type"]
    assert "javascript" in content_type or "text/" in content_type
    assert len(resp.text) > 100  # should be a real JS file


@pytest.mark.asyncio
async def test_captures_static_serving(bridge_server, test_page_server):
    """After a capture, GET /captures/capture_latest.png returns the PNG."""
    base_url, captures_dir = bridge_server
    payload = _element_capture_payload(test_page_server)

    async with httpx.AsyncClient() as client:
        # First create a capture
        resp = await client.post(
            f"{base_url}/api/capture", json=payload, timeout=30
        )
        assert resp.status_code == 200

        # Then fetch the PNG via static serving
        resp = await client.get(
            f"{base_url}/captures/capture_latest.png", timeout=30
        )
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/png"
        assert resp.content[:4] == b"\x89PNG"
