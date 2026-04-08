"""Standalone Playwright screenshot function.

Used by both the Bridge Server (server.py) and MCP Server (mcp_server.py).
Each caller manages its own Playwright browser lifecycle and passes the
browser instance in.
"""

import asyncio
import ipaddress
from urllib.parse import urlparse

# Blocked public domains to prevent SSRF to external services
BLOCKED_PUBLIC_DOMAINS = {"google.com", "github.com", "amazonaws.com"}


def _is_local_or_lan(hostname: str) -> bool:
    """Check if hostname is localhost, LAN, or a local dev domain."""
    # Explicit localhost variants
    if hostname in ("localhost", "0.0.0.0", "::1"):
        return True
    # Local dev domains (.local, .test, .internal, .localhost)
    if any(hostname.endswith(suffix) for suffix in (".local", ".test", ".internal", ".localhost")):
        return True
    # IP address check — allow private/loopback, reject public and link-local
    try:
        addr = ipaddress.ip_address(hostname)
        if addr.is_link_local:
            return False  # Block 169.254.x.x (cloud metadata endpoint)
        return addr.is_private or addr.is_loopback
    except ValueError:
        pass
    # Reject hex/octal IP encoding tricks (SSRF bypass)
    if hostname.startswith("0x") or hostname.startswith("0o") or hostname.replace(".", "").isdigit():
        return False
    # Unknown hostname — only allow if it looks like a local dev name
    # (contains no dots = simple hostname like "myserver", or is a known safe pattern)
    if "." not in hostname:
        return True  # Simple hostname like "myserver" — likely local
    # Reject everything else (public domains, subdomain tricks like localhost.evil.com)
    return False


def validate_url(url):
    """Restrict URLs to local/LAN addresses to prevent SSRF."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Unsupported URL scheme: {parsed.scheme}")
    # Reject userinfo in URL (e.g. http://evil.com@localhost) — SSRF bypass
    if "@" in (parsed.netloc or ""):
        raise ValueError(f"URL must not contain userinfo (@), got: {parsed.netloc}")
    if not _is_local_or_lan(parsed.hostname):
        raise ValueError(f"URL host must be localhost or LAN address, got: {parsed.hostname}")
    return url


async def take_screenshot(browser, url, scroll_x=0, scroll_y=0, width=1280, height=800, clip=None):
    """Take a screenshot via Playwright headless Chromium.

    Args:
        browser: Playwright Browser instance (caller manages lifecycle)
        url: Page URL to screenshot
        scroll_x: Horizontal scroll position in pixels
        scroll_y: Vertical scroll position in pixels
        width: Viewport width
        height: Viewport height
        clip: Optional dict with x, y, width, height to clip a region

    Returns:
        PNG screenshot as bytes

    Raises:
        ValueError: If URL is not localhost
    """
    validate_url(url)

    context = await browser.new_context(viewport={"width": width, "height": height})
    try:
        page = await context.new_page()
        try:
            await page.goto(url, wait_until="networkidle", timeout=15000)
        except Exception:
            await page.goto(url, wait_until="load", timeout=10000)

        await asyncio.sleep(1.5)

        if scroll_x or scroll_y:
            await page.evaluate("([x, y]) => window.scrollTo(x, y)", [int(scroll_x), int(scroll_y)])
            await asyncio.sleep(0.3)

        kwargs = {}
        if clip:
            kwargs["clip"] = {
                "x": clip["x"], "y": clip["y"],
                "width": clip["width"], "height": clip["height"],
            }

        screenshot = await page.screenshot(**kwargs)
        return screenshot
    finally:
        await context.close()
