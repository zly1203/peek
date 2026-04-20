"""End-to-end tests with real Playwright browser.

These tests verify the actual screenshot pipeline works — no mocks.
They start a simple HTTP server, take real screenshots, and verify output.
"""

import json
import socket
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler

import pytest
import pytest_asyncio
from playwright.async_api import async_playwright

from src.screenshot import take_screenshot


# ─── Simple test HTTP server ───

TEST_HTML = """<!DOCTYPE html>
<html>
<head><title>Test Page</title></head>
<body>
  <h1 id="title">Hello Peek</h1>
  <p class="content">This is a test page for E2E testing.</p>
</body>
</html>"""


class _Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(TEST_HTML.encode())

    def log_message(self, format, *args):
        pass


def _find_free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def test_server():
    """Start a real HTTP server on a free port."""
    port = _find_free_port()
    server = HTTPServer(("127.0.0.1", port), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}"
    server.shutdown()


@pytest_asyncio.fixture
async def browser():
    """Launch a real async Playwright browser."""
    pw = await async_playwright().start()
    b = await pw.chromium.launch(headless=True)
    yield b
    await b.close()
    await pw.stop()


# ─── Tests ───

@pytest.mark.asyncio
async def test_real_screenshot(test_server, browser):
    """Take a real screenshot and verify it's a valid PNG."""
    result = await take_screenshot(browser, test_server)

    assert isinstance(result, bytes)
    assert len(result) > 100
    assert result[:8] == b"\x89PNG\r\n\x1a\n"


@pytest.mark.asyncio
async def test_real_screenshot_custom_viewport(test_server, browser):
    """Different viewport sizes produce different image sizes."""
    small = await take_screenshot(browser, test_server, width=400, height=300)
    large = await take_screenshot(browser, test_server, width=1920, height=1080)

    assert small[:8] == b"\x89PNG\r\n\x1a\n"
    assert large[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(large) > len(small)


@pytest.mark.asyncio
async def test_real_screenshot_with_clip(test_server, browser):
    """Clip region produces smaller image than full page."""
    full = await take_screenshot(browser, test_server)
    clipped = await take_screenshot(
        browser, test_server,
        clip={"x": 0, "y": 0, "width": 200, "height": 100},
    )

    assert clipped[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(clipped) < len(full)


@pytest.mark.asyncio
async def test_url_validation_blocks_external(browser):
    """SSRF protection: external URLs are rejected."""
    with pytest.raises(ValueError, match="must be localhost"):
        await take_screenshot(browser, "http://example.com")


@pytest.mark.asyncio
async def test_mcp_roundtrip(test_server, browser):
    """Full roundtrip: screenshot → save → get_user_selection reads it back."""
    import base64
    from src.mcp_server import get_user_selection, CAPTURES_DIR

    png_bytes = await take_screenshot(browser, test_server)
    (CAPTURES_DIR / "capture_latest.png").write_bytes(png_bytes)

    metadata = {
        "mode": "region",
        "url": test_server,
        "viewport": {"width": 1280, "height": 800},
        "scroll": {"x": 0, "y": 0},
        "region": {"x": 0, "y": 0, "width": 400, "height": 300},
        "elements": [{"selector": "h1#title", "tagName": "h1", "text": "Hello Peek"}],
        "screenshot": "capture_latest.png",
        "timestamp": "20260316_150000",
    }
    (CAPTURES_DIR / "capture_latest.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False)
    )

    result = await get_user_selection()

    assert len(result) >= 2
    assert result[0].type == "text"
    returned_meta = json.loads(result[0].text)
    assert returned_meta["elements"][0]["text"] == "Hello Peek"

    assert result[1].type == "image"
    decoded = base64.b64decode(result[1].data)
    assert decoded == png_bytes
