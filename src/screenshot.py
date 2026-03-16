"""Standalone Playwright screenshot function.

Used by both the Bridge Server (server.py) and MCP Server (mcp_server.py).
Each caller manages its own Playwright browser lifecycle and passes the
browser instance in.
"""

import asyncio


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
    """
    context = await browser.new_context(viewport={"width": width, "height": height})
    page = await context.new_page()
    try:
        await page.goto(url, wait_until="networkidle", timeout=15000)
    except Exception:
        await page.goto(url, wait_until="load", timeout=10000)

    await asyncio.sleep(1.5)

    if scroll_x or scroll_y:
        await page.evaluate(f"window.scrollTo({scroll_x}, {scroll_y})")
        await asyncio.sleep(0.3)

    kwargs = {}
    if clip:
        kwargs["clip"] = {
            "x": clip["x"], "y": clip["y"],
            "width": clip["width"], "height": clip["height"],
        }

    screenshot = await page.screenshot(**kwargs)
    await context.close()
    return screenshot
