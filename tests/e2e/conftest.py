"""Shared fixtures for E2E tests.

Provides real bridge server, test page server, and Playwright browser.
NOTE: Up to 3 Chromium instances may run simultaneously (~600MB combined):
one owned by bridge server (for screenshots), one by test harness (for automation),
and one lazily started by MCP tool tests.
"""

import asyncio
import os
import socket
import shutil
import threading
import time
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from functools import partial

import httpx
import pytest
import pytest_asyncio
from playwright.async_api import async_playwright


FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _find_free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ─── Test page server ───


class _TestPageHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, directory=None, **kwargs):
        super().__init__(*args, directory=directory, **kwargs)

    def log_message(self, format, *args):
        pass  # suppress logs


@pytest.fixture(scope="session")
def test_page_server():
    """Serve test_page.html on a free port. Yields base URL."""
    port = _find_free_port()
    handler = partial(_TestPageHandler, directory=str(FIXTURES_DIR))
    server = HTTPServer(("127.0.0.1", port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}/test_page.html"
    server.shutdown()


# ─── Bridge server ───


@pytest.fixture(scope="session")
def _captures_tmpdir(tmp_path_factory):
    """Session-scoped temp directory for captures."""
    return tmp_path_factory.mktemp("captures")


@pytest.fixture(scope="session")
def bridge_server(_captures_tmpdir):
    """Start real bridge server with CAPTURES_DIR pointing to temp dir.

    Yields (base_url, captures_dir_path).
    """
    import uvicorn

    port = _find_free_port()

    # Set env var BEFORE importing server module so CAPTURES_DIR picks it up
    os.environ["PEEK_CAPTURES_DIR"] = str(_captures_tmpdir)

    # Force re-import of server module with new CAPTURES_DIR
    import importlib
    import src.server
    importlib.reload(src.server)
    from src.server import app

    # Also reload mcp_server so its CAPTURES_DIR matches
    import src.mcp_server
    importlib.reload(src.mcp_server)

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    # Wait for server to be ready
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            resp = httpx.get(f"http://127.0.0.1:{port}/")
            if resp.status_code == 200:
                break
        except httpx.ConnectError:
            time.sleep(0.1)
    else:
        raise RuntimeError("Bridge server did not start within 10s")

    yield f"http://127.0.0.1:{port}", _captures_tmpdir

    server.should_exit = True
    # Clean up env var
    os.environ.pop("PEEK_CAPTURES_DIR", None)


@pytest.fixture(scope="session")
def bridge_port(bridge_server):
    """Extract port from bridge_server URL for convenience."""
    base_url, _ = bridge_server
    return int(base_url.split(":")[-1])


# ─── Clean captures between tests ───


@pytest.fixture(autouse=True)
def clean_captures(_captures_tmpdir):
    """Delete all files in captures dir before each test."""
    for f in _captures_tmpdir.iterdir():
        if f.is_file():
            f.unlink()
    yield


# ─── Playwright browser (test-side, for bookmarklet automation) ───


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def pw_browser():
    """Real Playwright Chromium for test automation."""
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    yield browser
    await browser.close()
    await pw.stop()


@pytest_asyncio.fixture(loop_scope="session")
async def pw_page(pw_browser):
    """Fresh Playwright page per test."""
    context = await pw_browser.new_context(viewport={"width": 1280, "height": 800})
    page = await context.new_page()
    yield page
    await context.close()
