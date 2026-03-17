"""Unit tests for src/screenshot.py — take_screenshot function."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from src.screenshot import take_screenshot, validate_url


@pytest.fixture
def mock_browser():
    """Create a mock Playwright browser with context/page chain."""
    page = AsyncMock()
    page.goto = AsyncMock()
    page.evaluate = AsyncMock()
    page.screenshot = AsyncMock(return_value=b"fake_png_bytes")

    context = AsyncMock()
    context.new_page = AsyncMock(return_value=page)
    context.close = AsyncMock()

    browser = AsyncMock()
    browser.new_context = AsyncMock(return_value=context)

    return browser, context, page


@pytest.mark.asyncio
async def test_take_screenshot_basic(mock_browser):
    """Basic screenshot with default params."""
    browser, context, page = mock_browser

    result = await take_screenshot(browser, "http://localhost:3000")

    browser.new_context.assert_called_once_with(viewport={"width": 1280, "height": 800})
    page.goto.assert_called_once_with("http://localhost:3000", wait_until="networkidle", timeout=15000)
    page.screenshot.assert_called_once_with()
    context.close.assert_called_once()
    assert result == b"fake_png_bytes"


@pytest.mark.asyncio
async def test_take_screenshot_custom_viewport(mock_browser):
    """Screenshot with custom width/height."""
    browser, context, page = mock_browser

    await take_screenshot(browser, "http://localhost:3000", width=800, height=600)

    browser.new_context.assert_called_once_with(viewport={"width": 800, "height": 600})


@pytest.mark.asyncio
async def test_take_screenshot_with_scroll(mock_browser):
    """Screenshot with scroll position."""
    browser, context, page = mock_browser

    await take_screenshot(browser, "http://localhost:3000", scroll_x=100, scroll_y=500)

    page.evaluate.assert_called_once_with("([x, y]) => window.scrollTo(x, y)", [100, 500])


@pytest.mark.asyncio
async def test_take_screenshot_no_scroll_when_zero(mock_browser):
    """No scrollTo call when scroll is 0."""
    browser, context, page = mock_browser

    await take_screenshot(browser, "http://localhost:3000", scroll_x=0, scroll_y=0)

    page.evaluate.assert_not_called()


@pytest.mark.asyncio
async def test_take_screenshot_with_clip(mock_browser):
    """Screenshot with clip region."""
    browser, context, page = mock_browser
    clip = {"x": 10, "y": 20, "width": 300, "height": 200}

    await take_screenshot(browser, "http://localhost:3000", clip=clip)

    page.screenshot.assert_called_once_with(clip={"x": 10, "y": 20, "width": 300, "height": 200})


@pytest.mark.asyncio
async def test_take_screenshot_networkidle_fallback(mock_browser):
    """Falls back to 'load' when networkidle times out."""
    browser, context, page = mock_browser
    # First goto (networkidle) fails, second (load) succeeds
    page.goto = AsyncMock(side_effect=[Exception("timeout"), None])

    result = await take_screenshot(browser, "http://localhost:3000")

    assert page.goto.call_count == 2
    assert page.goto.call_args_list[1].kwargs["wait_until"] == "load"
    assert result == b"fake_png_bytes"


@pytest.mark.asyncio
async def test_take_screenshot_context_closed_on_success(mock_browser):
    """Context is closed after successful screenshot."""
    browser, context, page = mock_browser

    await take_screenshot(browser, "http://localhost:3000")

    context.close.assert_called_once()


@pytest.mark.asyncio
async def test_take_screenshot_context_closed_on_error(mock_browser):
    """Context is closed even when screenshot fails."""
    browser, context, page = mock_browser
    page.screenshot = AsyncMock(side_effect=Exception("screenshot failed"))

    with pytest.raises(Exception, match="screenshot failed"):
        await take_screenshot(browser, "http://localhost:3000")

    context.close.assert_called_once()


# ─── URL validation tests ───

def test_validate_url_localhost():
    """Accepts localhost URLs."""
    assert validate_url("http://localhost:3000") == "http://localhost:3000"
    assert validate_url("http://127.0.0.1:8080") == "http://127.0.0.1:8080"
    assert validate_url("https://localhost:443/path") == "https://localhost:443/path"


def test_validate_url_rejects_external():
    """Rejects non-localhost URLs."""
    with pytest.raises(ValueError, match="must be localhost"):
        validate_url("http://example.com")
    with pytest.raises(ValueError, match="must be localhost"):
        validate_url("http://192.168.1.1/admin")
    with pytest.raises(ValueError, match="must be localhost"):
        validate_url("http://169.254.169.254/latest/meta-data/")


def test_validate_url_rejects_file_scheme():
    """Rejects file:// URLs."""
    with pytest.raises(ValueError, match="Unsupported URL scheme"):
        validate_url("file:///etc/passwd")


def test_validate_url_rejects_javascript():
    """Rejects javascript: URLs."""
    with pytest.raises(ValueError, match="Unsupported URL scheme"):
        validate_url("javascript:alert(1)")
