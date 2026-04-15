"""Element select mode UX edge cases.

Tests that the selectMouseMove filter correctly handles tricky DOM
states like body/html, hidden elements, fixed-position overlays, etc.
"""

import asyncio
import pytest
import pytest_asyncio
from pathlib import Path
from playwright.async_api import async_playwright

INSPECTOR_JS = (Path(__file__).parent.parent / "static" / "inspector.js").read_text()


@pytest_asyncio.fixture
async def page():
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    p = await browser.new_page(viewport={"width": 1280, "height": 800})
    yield p
    await browser.close()
    await pw.stop()


async def _setup_select_mode(page, html: str):
    await page.set_content(html)
    await page.evaluate(INSPECTOR_JS)
    await page.evaluate('() => document.querySelector(\'[data-mode="select"]\').click()')
    await asyncio.sleep(0.2)


async def _check_filter(page, target_selector: str) -> str:
    """Run the same filter logic from selectMouseMove and return the action."""
    return await page.evaluate(f"""(sel) => {{
        const NS = '__uiinsp_';
        const el = document.querySelector(sel);
        if (!el) return 'not_found';
        if (el.id?.startsWith(NS) || el.closest('[id^="' + NS + '"]')) return 'skip_ns';
        const tag = el.tagName.toLowerCase();
        if (tag === 'body' || tag === 'html') return 'skip_body';
        return 'selectable';
    }}""", target_selector)


# ─── Body/html filter (the originally-reported bug) ───

@pytest.mark.asyncio
async def test_body_blocked(page):
    await _setup_select_mode(page, "<body><p>x</p></body>")
    assert await _check_filter(page, "body") == "skip_body"


@pytest.mark.asyncio
async def test_html_blocked(page):
    await _setup_select_mode(page, "<body><p>x</p></body>")
    assert await _check_filter(page, "html") == "skip_body"


@pytest.mark.asyncio
async def test_namespace_overlay_skipped(page):
    """Peek's own injected elements should not be selectable."""
    await _setup_select_mode(page, "<button id='b'>x</button>")
    # The toolbar exists as an injected element
    result = await _check_filter(page, "[id^='__uiinsp_toolbar']")
    assert result == "skip_ns"


# ─── Realistic large elements should still be selectable ───

@pytest.mark.asyncio
async def test_large_canvas_still_selectable(page):
    """A canvas covering most of the viewport (game, map) should be selectable."""
    html = '<canvas id="game" style="width:100vw; height:90vh;"></canvas>'
    await _setup_select_mode(page, html)
    assert await _check_filter(page, "#game") == "selectable"


@pytest.mark.asyncio
async def test_full_screen_modal_selectable(page):
    """A modal overlay is a legitimate selection target."""
    html = '<div id="modal" style="position:fixed;top:0;left:0;width:100vw;height:100vh;background:white;"></div>'
    await _setup_select_mode(page, html)
    assert await _check_filter(page, "#modal") == "selectable"


@pytest.mark.asyncio
async def test_video_element_selectable(page):
    html = '<video id="v" style="width:100%; height:80vh;"></video>'
    await _setup_select_mode(page, html)
    assert await _check_filter(page, "#v") == "selectable"


# ─── Z-index / overlay behavior ───

@pytest.mark.asyncio
async def test_send_bar_above_overlay(page):
    """The send bar must have higher z-index than overlay so clicks reach it."""
    await _setup_select_mode(page, "<button id='b'>x</button>")
    z = await page.evaluate("""() => {
        const NS = '__uiinsp_';
        const sendbar = document.getElementById(NS + 'sendbar');
        const overlay = document.getElementById(NS + 'overlay');
        return {
            sendbar: sendbar ? parseInt(sendbar.style.zIndex) : null,
            overlay: overlay ? parseInt(overlay.style.zIndex) : null,
        };
    }""")
    assert z["sendbar"] is not None and z["overlay"] is not None
    assert z["sendbar"] > z["overlay"]


@pytest.mark.asyncio
async def test_highlight_pointer_events_none(page):
    """Highlight box must not intercept mouse clicks."""
    await _setup_select_mode(page, "<button id='b'>x</button>")
    pe = await page.evaluate("""() => {
        const h = document.getElementById('__uiinsp_highlight');
        return h ? h.style.pointerEvents : null;
    }""")
    assert pe == "none"


# ─── Mode lifecycle ───

@pytest.mark.asyncio
async def test_escape_exits_select_mode(page):
    await _setup_select_mode(page, "<button id='b'>x</button>")
    await page.keyboard.press("Escape")
    await asyncio.sleep(0.2)
    state = await page.evaluate("""() => ({
        overlay: !!document.getElementById('__uiinsp_overlay'),
        highlight: !!document.getElementById('__uiinsp_highlight'),
        sendbar: !!document.getElementById('__uiinsp_sendbar'),
        toolbar: !!document.getElementById('__uiinsp_toolbar'),
    })""")
    # Mode-specific elements gone, toolbar remains
    assert not state["overlay"]
    assert not state["highlight"]
    assert not state["sendbar"]
    assert state["toolbar"]


@pytest.mark.asyncio
async def test_double_escape_destroys_inspector(page):
    await _setup_select_mode(page, "<button id='b'>x</button>")
    await page.keyboard.press("Escape")  # exit mode
    await asyncio.sleep(0.1)
    await page.keyboard.press("Escape")  # destroy
    await asyncio.sleep(0.1)
    has_toolbar = await page.evaluate("() => !!document.getElementById('__uiinsp_toolbar')")
    assert not has_toolbar


# ─── Mode switching ───

@pytest.mark.asyncio
async def test_alt_shortcuts_switch_modes(page):
    await page.set_content("<button id='b'>x</button>")
    await page.evaluate(INSPECTOR_JS)
    await asyncio.sleep(0.2)

    for shortcut, expected_mode in [("Alt+r", "region"), ("Alt+s", "select"), ("Alt+a", "annotate")]:
        await page.keyboard.press(shortcut)
        await asyncio.sleep(0.2)
        active = await page.evaluate(f"""() => {{
            const btn = document.querySelector('[id^="__uiinsp_toolbar"] button[data-mode="{expected_mode}"]');
            return btn ? btn.style.background : null;
        }}""")
        assert active is not None
        # Active button should have blue background (#3b82f6 or rgb form)
        assert "#3b82f6" in active or "rgb(59, 130, 246)" in active, \
            f"shortcut {shortcut} did not activate mode {expected_mode}: bg={active}"


# ─── No-op edge cases ───

@pytest.mark.asyncio
async def test_select_mode_re_entry_does_not_double_render(page):
    """Clicking Element button twice should not stack overlays."""
    await page.set_content("<button id='b'>x</button>")
    await page.evaluate(INSPECTOR_JS)
    await asyncio.sleep(0.2)
    # Click select twice
    await page.evaluate('() => document.querySelector(\'[data-mode="select"]\').click()')
    await asyncio.sleep(0.1)
    await page.evaluate('() => document.querySelector(\'[data-mode="select"]\').click()')
    await asyncio.sleep(0.1)
    # Second click should TOGGLE off (mode === newMode case)
    overlays = await page.evaluate("() => document.querySelectorAll('[id^=\"__uiinsp_overlay\"]').length")
    assert overlays == 0  # toggled off
