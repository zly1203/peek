"""Shared helpers for E2E tests."""

import asyncio
import time
from pathlib import Path

import httpx


async def wait_for_capture(bridge_url: str, timeout: float = 5.0) -> dict:
    """Poll bridge server until a capture appears or timeout.

    Returns the capture JSON dict, or raises TimeoutError.
    """
    deadline = time.monotonic() + timeout
    async with httpx.AsyncClient() as client:
        while time.monotonic() < deadline:
            resp = await client.get(f"{bridge_url}/api/capture/latest")
            if resp.status_code == 200:
                return resp.json()
            await asyncio.sleep(0.2)
    raise TimeoutError(f"No capture appeared within {timeout}s")


async def wait_for_new_capture(
    bridge_url: str, previous_ts: str | None, timeout: float = 5.0
) -> dict:
    """Poll until a capture with a different timestamp than previous_ts appears."""
    deadline = time.monotonic() + timeout
    async with httpx.AsyncClient() as client:
        while time.monotonic() < deadline:
            resp = await client.get(f"{bridge_url}/api/capture/latest")
            if resp.status_code == 200:
                data = resp.json()
                if data.get("timestamp") and data["timestamp"] != previous_ts:
                    return data
            await asyncio.sleep(0.2)
    raise TimeoutError(f"No new capture within {timeout}s")


def inject_inspector_js(page, bridge_port: int) -> str:
    """Read inspector.js, return modified source with bridge port override.

    Usage: await page.add_script_tag(content=inject_inspector_js(page, port))
    """
    js_path = Path(__file__).resolve().parent.parent.parent / "static" / "inspector.js"
    js_source = js_path.read_text()
    # Prepend the bridge URL override before the IIFE
    return f"window.__PEEK_BRIDGE_URL = 'http://localhost:{bridge_port}';\n{js_source}"
