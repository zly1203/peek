"""MCP Server for Peek.

Exposes two tools to Claude Code via stdio:
- screenshot: take a screenshot of any URL
- get_latest_capture: retrieve the latest bookmarklet capture

Also launches the Bridge Server in a background thread so bookmarklet
data flows in while MCP serves Claude Code.
"""

import sys
import json
import base64
import asyncio
import logging
import threading
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from playwright.async_api import async_playwright

from .screenshot import take_screenshot

# All logging must go to stderr (stdout is MCP stdio transport)
logging.basicConfig(level=logging.INFO, stream=sys.stderr)
logger = logging.getLogger("peek")

BASE_DIR = Path(__file__).resolve().parent.parent
CAPTURES_DIR = BASE_DIR / "captures"
CAPTURES_DIR.mkdir(exist_ok=True)

# ─── MCP Server ───

mcp = FastMCP(name="peek")

# Playwright browser (managed per MCP server lifecycle)
_pw = None
_browser = None


async def _ensure_browser():
    """Lazily start Playwright browser on first tool call."""
    global _pw, _browser
    if _browser is None:
        _pw = await async_playwright().start()
        _browser = await _pw.chromium.launch(headless=True)
        logger.info("Playwright Chromium launched (MCP)")
    return _browser


async def _shutdown_browser():
    """Close Playwright browser."""
    global _pw, _browser
    if _browser:
        await _browser.close()
        _browser = None
    if _pw:
        await _pw.stop()
        _pw = None


@mcp.tool()
async def screenshot(
    url: str,
    scroll_y: int = 0,
    width: int = 1280,
    height: int = 800,
) -> list:
    """Take a screenshot of any URL via Playwright headless Chromium.

    Use this to visually inspect a web page. Can be used after modifying
    UI code to verify visual changes.

    Args:
        url: The page URL to screenshot (e.g. http://localhost:3000)
        scroll_y: Vertical scroll position in pixels (default: 0)
        width: Viewport width in pixels (default: 1280)
        height: Viewport height in pixels (default: 800)
    """
    from mcp.types import TextContent, ImageContent

    try:
        browser = await _ensure_browser()
        png_bytes = await take_screenshot(
            browser, url,
            scroll_y=scroll_y, width=width, height=height,
        )
        return [
            ImageContent(
                type="image",
                data=base64.b64encode(png_bytes).decode(),
                mimeType="image/png",
            )
        ]
    except Exception as e:
        return [TextContent(type="text", text=f"Screenshot failed: {e}")]


@mcp.tool()
async def get_latest_capture() -> list:
    """Get the latest capture from the Peek bookmarklet.

    Returns the screenshot image, element metadata (selectors, styles,
    bounding boxes), and annotation overlay if available. Use this after
    the user has selected a region, element, or drawn annotations in
    their browser.
    """
    from mcp.types import TextContent, ImageContent

    json_path = CAPTURES_DIR / "capture_latest.json"
    png_path = CAPTURES_DIR / "capture_latest.png"
    annot_path = CAPTURES_DIR / "capture_latest_annot.png"

    if not json_path.exists():
        return [TextContent(
            type="text",
            text="No captures yet. Use the bookmarklet to capture a region, element, or annotation.",
        )]

    result = []

    # JSON metadata
    metadata = json.loads(json_path.read_text())
    result.append(TextContent(type="text", text=json.dumps(metadata, indent=2, ensure_ascii=False)))

    # Screenshot
    if png_path.exists():
        png_b64 = base64.b64encode(png_path.read_bytes()).decode()
        result.append(ImageContent(type="image", data=png_b64, mimeType="image/png"))

    # Annotation overlay (annotate mode only)
    if annot_path.exists() and metadata.get("annotationOverlay"):
        annot_b64 = base64.b64encode(annot_path.read_bytes()).decode()
        result.append(ImageContent(type="image", data=annot_b64, mimeType="image/png"))

    return result


# ─── Bridge Server background thread ───

_bridge_server = None  # uvicorn.Server reference for graceful shutdown


def _run_bridge_server(host: str, port: int):
    """Run the FastAPI bridge server in a background thread with its own event loop."""
    global _bridge_server
    import uvicorn
    from .server import app

    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    _bridge_server = uvicorn.Server(config)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_bridge_server.serve())
    except OSError as e:
        if "address already in use" in str(e).lower() or e.errno == 48:
            logger.warning(f"Port {port} already in use — bridge server skipped (MCP tools still work)")
        else:
            raise
    finally:
        loop.close()


def run(host: str = "127.0.0.1", port: int = 8899):
    """Start the MCP server (stdio) with embedded Bridge Server."""
    # Start bridge in background thread
    bridge_thread = threading.Thread(
        target=_run_bridge_server,
        args=(host, port),
        daemon=True,
    )
    bridge_thread.start()
    logger.info(f"Bridge server started on {host}:{port}")

    # Run MCP server on main thread (stdio)
    try:
        mcp.run()
    finally:
        # Graceful shutdown of bridge server and browser
        if _bridge_server:
            _bridge_server.should_exit = True
        try:
            asyncio.get_event_loop().run_until_complete(_shutdown_browser())
        except Exception:
            pass


if __name__ == "__main__":
    run()
