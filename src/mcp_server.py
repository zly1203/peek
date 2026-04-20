"""MCP Server for Peek.

Exposes two tools to Claude Code via stdio:
- screenshot: take a screenshot of any URL (default for viewing pages)
- get_user_selection: read what the user just captured with the bookmarklet

Also launches the Bridge Server in a background thread so bookmarklet
data flows in while MCP serves Claude Code.
"""

import sys
import os
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
CAPTURES_DIR = Path(os.environ.get("PEEK_CAPTURES_DIR", str(Path.home() / ".peek" / "captures")))
CAPTURES_DIR.mkdir(parents=True, exist_ok=True)

# ─── MCP Server ───

mcp = FastMCP(name="peek")

# Playwright browser (managed per MCP server lifecycle)
_pw = None
_browser = None


async def _ensure_browser():
    """Lazily start Playwright browser on first tool call."""
    global _pw, _browser
    if _browser is None:
        try:
            _pw = await async_playwright().start()
            _browser = await _pw.chromium.launch(headless=True)
            logger.info("Playwright Chromium launched (MCP)")
        except Exception as e:
            if "Executable doesn't exist" in str(e) or "browserType.launch" in str(e):
                raise RuntimeError(
                    "Playwright Chromium is not installed. Run: playwright install chromium"
                ) from e
            raise
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


def _translate_screenshot_error(e: Exception, url: str) -> str:
    """Turn raw Playwright/validation errors into user-readable guidance."""
    msg = str(e)
    if "ERR_CONNECTION_REFUSED" in msg:
        return f"Could not connect to {url}. Is your dev server running on this port? Double-check the port in your request."
    if "ERR_NAME_NOT_RESOLVED" in msg:
        return f"Could not resolve the hostname in {url}. Check the URL spelling, or verify your .local/.test domain is set up on this machine."
    if "URL host must be" in msg or "Unsupported URL scheme" in msg or "must not contain userinfo" in msg:
        return "Peek only supports local/LAN URLs (localhost, 127.0.0.1, private IPs, .local/.test). Public URLs are blocked for safety."
    if "Timeout" in msg or "timeout" in msg.lower():
        return f"Page at {url} didn't load within 15 seconds. Your server may be slow or stuck — check the server logs."
    if "Playwright Chromium is not installed" in msg or "Executable doesn't exist" in msg:
        return "Playwright Chromium is not installed. Run: playwright install chromium"
    return f"Screenshot failed: {msg}. If this persists, the page may have crashed or Playwright may need reinstalling."


@mcp.tool()
async def screenshot(
    url: str,
    scroll_y: int = 0,
    width: int = 1280,
    height: int = 800,
) -> list:
    """Take a headless screenshot of any local/LAN URL.

    Use when the user specifies a URL, or wants a fresh page render
    (e.g. verifying UI after code edits). Renders in a fresh headless
    Chromium session — no cookies, no login state, no user interactions.

    For ambiguous requests ("look at it", "check it", "看一下"), prefer
    `get_user_selection` first — the user may have clicked the Peek
    bookmarklet on the thing they want you to see. Only fall back to
    this `screenshot` tool if no capture exists or it's clearly stale.

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
        return [TextContent(type="text", text=_translate_screenshot_error(e, url))]


@mcp.tool()
async def get_user_selection() -> list:
    """Read what the user captured with the Peek bookmarklet.

    This is the primary tool for seeing what the user is pointing at.
    Use it when:
      - The user references their selection/click/drawing
        ("check what I selected", "look at the element I pointed at",
         "see my annotation")
      - The user's request is ambiguous ("look at it", "check it",
        "看一下") — a fresh capture is usually what they mean.

    Returns screenshot + element metadata (selectors, styles, bounding
    boxes, ancestor chain, sibling position, parent layout) + annotation
    overlay if drawn. Metadata includes `age_seconds` (how long since
    the bookmarklet was clicked) and `url` (the page it was captured on).

    If `age_seconds` is clearly old (e.g. hours) AND the user did not
    reference their selection, call `screenshot(url)` using the `url`
    from this metadata for a fresh render of the same page.
    """
    from mcp.types import TextContent, ImageContent
    import time

    json_path = CAPTURES_DIR / "capture_latest.json"
    png_path = CAPTURES_DIR / "capture_latest.png"
    annot_path = CAPTURES_DIR / "capture_latest_annot.png"

    if not json_path.exists():
        return [TextContent(
            type="text",
            text="No captures yet. Use the bookmarklet to capture a region, element, or annotation.",
        )]

    result = []

    # JSON metadata — annotate with age_seconds so the agent can judge freshness
    try:
        metadata = json.loads(json_path.read_text())
    except json.JSONDecodeError:
        return [TextContent(
            type="text",
            text="Capture file is corrupted. Click the Peek bookmarklet again to create a fresh capture.",
        )]
    ts = metadata.get("timestamp")
    if ts:
        try:
            from datetime import datetime
            capture_time = datetime.strptime(ts, "%Y%m%d_%H%M%S").timestamp()
            metadata["age_seconds"] = int(time.time() - capture_time)
        except Exception:
            pass
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

    # If launched manually (TTY), show friendly setup instructions.
    # If launched by an MCP client (no TTY), just log briefly.
    if sys.stdin.isatty():
        url = f"http://{host}:{port}"
        print(
            f"\n  Peek is running on {url}\n\n"
            f"  Next steps:\n"
            f"    1. Open {url} in your browser\n"
            f"    2. Drag the blue 'Peek' button to your bookmark bar\n"
            f"    3. Click the bookmarklet on any localhost page to start capturing\n\n"
            f"  Press Ctrl+C to stop.\n",
            file=sys.stderr,
        )
    else:
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
