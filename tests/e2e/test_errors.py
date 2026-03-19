"""Layer C: Edge cases and error handling tests."""

import asyncio
import time
import socket
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

import httpx
import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.errors]


# ─── Helper: find a free port ───


def _find_free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ─── Helper: element capture payload ───


def _element_capture_payload(page_url: str) -> dict:
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


# ═══════════════════════════════════════════════════════════════════════
# Request boundaries (3)
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_post_empty_json(bridge_server):
    """POST /api/capture with {} -> still returns 200 (KeyError caught),
    screenshot is None, server remains responsive."""
    base_url, _ = bridge_server

    async with httpx.AsyncClient() as client:
        resp = await client.post(f"{base_url}/api/capture", json={}, timeout=30)
        # The KeyError on data["url"] is caught by the try/except in receive_capture,
        # so the endpoint still returns 200 with screenshot=None
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"

        # Server should still respond after the error
        resp2 = await client.get(f"{base_url}/", timeout=30)
        assert resp2.status_code == 200


@pytest.mark.asyncio
async def test_post_non_json_body(bridge_server):
    """POST plain text to /api/capture -> 400 or 422 or 500."""
    base_url, _ = bridge_server

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{base_url}/api/capture",
            content=b"this is not json",
            headers={"Content-Type": "text/plain"},
            timeout=30,
        )
        assert resp.status_code in (400, 422, 500)


@pytest.mark.asyncio
async def test_post_oversized_body(bridge_server):
    """POST with Content-Length exceeding 50MB -> 413."""
    base_url, _ = bridge_server

    # Use a raw TCP/HTTP approach to send the oversized Content-Length header
    # without actually sending 60MB of data (httpx validates content-length mismatch).
    import urllib.parse
    parsed = urllib.parse.urlparse(base_url)
    host, port = parsed.hostname, parsed.port

    reader, writer = await asyncio.open_connection(host, port)
    try:
        request_line = (
            f"POST /api/capture HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {60 * 1024 * 1024}\r\n"
            f"\r\n"
        )
        writer.write(request_line.encode())
        await writer.drain()

        # Read response — server should reject before waiting for body
        response = await asyncio.wait_for(reader.read(4096), timeout=10)
        response_text = response.decode(errors="replace")
        assert "413" in response_text
    finally:
        writer.close()
        await writer.wait_closed()


# ═══════════════════════════════════════════════════════════════════════
# SSRF protection (4)
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_screenshot_rejects_external_url(bridge_server):
    """GET /api/screenshot?url=http://evil.com -> 500 (ValueError)."""
    base_url, _ = bridge_server

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{base_url}/api/screenshot",
            params={"url": "http://evil.com"},
            timeout=30,
        )
        assert resp.status_code == 500


@pytest.mark.asyncio
async def test_screenshot_rejects_file_scheme(bridge_server):
    """GET /api/screenshot?url=file:///etc/passwd -> 500."""
    base_url, _ = bridge_server

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{base_url}/api/screenshot",
            params={"url": "file:///etc/passwd"},
            timeout=30,
        )
        assert resp.status_code == 500


@pytest.mark.asyncio
async def test_screenshot_rejects_javascript_scheme(bridge_server):
    """GET /api/screenshot?url=javascript:alert(1) -> 500."""
    base_url, _ = bridge_server

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{base_url}/api/screenshot",
            params={"url": "javascript:alert(1)"},
            timeout=30,
        )
        assert resp.status_code == 500


@pytest.mark.asyncio
async def test_screenshot_no_url_param(bridge_server):
    """GET /api/screenshot without url param -> 422 (FastAPI missing param)."""
    base_url, _ = bridge_server

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{base_url}/api/screenshot",
            timeout=30,
        )
        assert resp.status_code == 422


# ═══════════════════════════════════════════════════════════════════════
# Page load failures (2)
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_screenshot_nonexistent_port(bridge_server):
    """Screenshot of unreachable localhost port -> 500, no hang."""
    base_url, _ = bridge_server

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{base_url}/api/screenshot",
            params={"url": "http://localhost:19999"},
            timeout=30,
        )
        assert resp.status_code == 500


class SlowHandler(BaseHTTPRequestHandler):
    """Handler that serves HTML quickly but has a resource that never completes
    on first request, then returns 404 quickly on subsequent requests.

    This simulates a page where networkidle will fail (first load: slow-resource
    blocks indefinitely) but the load fallback succeeds (second load: slow-resource
    returns 404 immediately, so the load event fires).
    """

    # Class-level counter tracks requests to /slow-resource
    slow_request_count = 0
    _lock = threading.Lock()

    def do_GET(self):
        if "/slow-resource" in self.path:
            with SlowHandler._lock:
                SlowHandler.slow_request_count += 1
                count = SlowHandler.slow_request_count
            if count <= 1:
                # First request: block forever (causes networkidle timeout)
                try:
                    time.sleep(300)
                except Exception:
                    pass
                return
            else:
                # Subsequent requests: return 404 quickly (load event can fire)
                self.send_response(404)
                self.end_headers()
                return
        # For all other paths, serve the HTML page
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(
            b"<!DOCTYPE html><html><body>"
            b"<h1>Slow</h1>"
            b'<img src="/slow-resource">'
            b"</body></html>"
        )

    def log_message(self, format, *args):
        pass


@pytest.mark.asyncio
async def test_screenshot_slow_page_fallback(bridge_server):
    """Page with never-completing resource -> networkidle times out,
    falls back to 'load', returns valid PNG. Takes ~15-20s."""
    base_url, _ = bridge_server

    # Reset counter for this test
    SlowHandler.slow_request_count = 0

    port = _find_free_port()
    from socketserver import ThreadingMixIn

    class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
        daemon_threads = True

    server = ThreadedHTTPServer(("127.0.0.1", port), SlowHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{base_url}/api/screenshot",
                params={"url": f"http://127.0.0.1:{port}/"},
                timeout=60,
            )
            assert resp.status_code == 200
            assert resp.content[:4] == b"\x89PNG"
            assert len(resp.content) > 100
    finally:
        server.shutdown()


# ═══════════════════════════════════════════════════════════════════════
# Concurrency (2)
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_concurrent_captures(bridge_server, test_page_server):
    """3 simultaneous capture POSTs -> all return 200."""
    base_url, captures_dir = bridge_server
    payload = _element_capture_payload(test_page_server)

    async def do_capture():
        async with httpx.AsyncClient() as client:
            return await client.post(
                f"{base_url}/api/capture", json=payload, timeout=30
            )

    results = await asyncio.gather(do_capture(), do_capture(), do_capture())

    for resp in results:
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    # Latest capture should exist with data from one of them
    latest_json = captures_dir / "capture_latest.json"
    assert latest_json.exists()


@pytest.mark.asyncio
async def test_concurrent_screenshots(bridge_server, test_page_server):
    """3 simultaneous screenshot requests -> all return valid PNGs."""
    base_url, _ = bridge_server

    async def do_screenshot():
        async with httpx.AsyncClient() as client:
            return await client.get(
                f"{base_url}/api/screenshot",
                params={"url": test_page_server},
                timeout=30,
            )

    results = await asyncio.gather(
        do_screenshot(), do_screenshot(), do_screenshot()
    )

    for resp in results:
        assert resp.status_code == 200
        assert resp.content[:4] == b"\x89PNG"
        assert len(resp.content) > 100


# ═══════════════════════════════════════════════════════════════════════
# MCP tool boundaries (3)
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_mcp_get_latest_no_captures(bridge_server):
    """get_latest_capture() with empty captures dir -> 'no captures' text."""
    # bridge_server fixture ensures PEEK_CAPTURES_DIR is set and modules reloaded
    from src.mcp_server import get_latest_capture

    result = await get_latest_capture()
    assert len(result) == 1
    assert result[0].type == "text"
    assert "no capture" in result[0].text.lower() or "No captures" in result[0].text


@pytest.mark.asyncio
async def test_mcp_screenshot_external_url(bridge_server):
    """screenshot(url='http://evil.com') -> error TextContent."""
    from src.mcp_server import screenshot

    result = await screenshot(url="http://evil.com")
    assert len(result) == 1
    assert result[0].type == "text"
    assert "failed" in result[0].text.lower() or "error" in result[0].text.lower()


@pytest.mark.asyncio
async def test_capture_works_in_clean_state(bridge_server, test_page_server):
    """POST capture in clean state -> 200, files created."""
    base_url, captures_dir = bridge_server
    payload = _element_capture_payload(test_page_server)

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{base_url}/api/capture", json=payload, timeout=30
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    assert (captures_dir / "capture_latest.json").exists()
    assert (captures_dir / "capture_latest.png").exists()


# ═══════════════════════════════════════════════════════════════════════
# Port conflict (1)
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_mcp_screenshot_works_independently(bridge_server, test_page_server):
    """MCP screenshot() works regardless of bridge server state,
    using its own lazy Playwright browser."""
    import src.mcp_server as mcp_mod
    from src.mcp_server import screenshot

    # Reset the MCP module's browser so it starts fresh in this event loop
    old_browser = mcp_mod._browser
    old_pw = mcp_mod._pw
    mcp_mod._browser = None
    mcp_mod._pw = None

    try:
        result = await screenshot(url=test_page_server, width=1280, height=800)
        assert len(result) == 1
        assert result[0].type == "image"
        assert result[0].mimeType == "image/png"

        import base64
        png_bytes = base64.b64decode(result[0].data)
        assert png_bytes[:4] == b"\x89PNG"
        assert len(png_bytes) > 100
    finally:
        # Clean up the browser we started, restore old state
        if mcp_mod._browser:
            await mcp_mod._browser.close()
        if mcp_mod._pw:
            await mcp_mod._pw.stop()
        mcp_mod._browser = old_browser
        mcp_mod._pw = old_pw
