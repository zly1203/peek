"""End-to-end tests for v0.5.14 / v0.5.15 capture-flow changes.

These tests use richer fixture pages than the original `test_page.html`
(which is 23 lines and has no lazy images, web fonts, or JS-modified DOM).
The pre-v0.5.14 inspector would time out at 30 s on `lazy_images.html`;
the post-fix path completes well under 3 s. Each test below targets a
distinct invariant that v0.5.14 / v0.5.15 introduced — see individual
docstrings for the specific behavior under test.
"""

import asyncio
import json
import time

import pytest

from tests.e2e.utils import inject_inspector_js, wait_for_capture

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.bookmarklet,
    pytest.mark.asyncio(loop_scope="session"),
]


def _fixture_url(test_page_server: str, name: str) -> str:
    """Translate the session-scoped `test_page_server` URL (which points at
    test_page.html) into the URL for any other fixture file in the same
    directory. Avoids needing a parallel fixture per page."""
    return test_page_server.replace("test_page.html", name)


async def _inject_and_wait(page, port):
    js = inject_inspector_js(page, port)
    await page.add_script_tag(content=js)
    await page.wait_for_selector("[id^='__uiinsp_toolbar']", timeout=5000)


async def _click_send(page):
    """See test_bookmarklet._click_send for rationale on dispatch_event."""
    await page.wait_for_selector(
        "#__uiinsp_subtoolbar_send", state="visible", timeout=3000
    )
    await page.dispatch_event("#__uiinsp_subtoolbar_send", "click")


# ─────────────────────────────────────────────────────────────────────
# 1. Lazy-image capture finishes quickly (eagerify + 2 s timeout)
# ─────────────────────────────────────────────────────────────────────


async def test_lazy_images_capture_succeeds_quickly(
    pw_page, test_page_server, bridge_server, bridge_port
):
    """The fixture has 4 `<img loading="lazy">` icons after a 1500-px
    spacer. Without scrolling, the browser hasn't fetched them, so their
    `complete` flag is false and they never fire `load`.

    Pre-v0.5.14: modern-screenshot's "wait until load" phase blocked for
    the full 30 s default timeout, then the capture eventually succeeded
    with broken images. This test asserts the post-fix path finishes the
    whole round-trip (capture + POST) in well under 3 s — the v0.5.14
    `eagerifyLazyImages` swap forces an immediate fetch, and the v0.5.14
    `timeout: 2000` caps any genuinely-stuck image at 2 s instead of 30.

    We use Annotate mode because it captures `documentElement`, which is
    the only mode whose target subtree includes the offscreen lazy
    images. Element/Region modes pick a smaller subtree that excludes
    them, so the eagerify path wouldn't be exercised.
    """
    url = _fixture_url(test_page_server, "lazy_images.html")
    await pw_page.goto(url)
    await _inject_and_wait(pw_page, bridge_port)

    await pw_page.keyboard.press("Alt+a")  # Annotate mode
    await asyncio.sleep(0.3)

    # Draw a small annotation stroke in the viewport (anywhere visible).
    await pw_page.mouse.move(150, 150)
    await pw_page.mouse.down()
    await pw_page.mouse.move(300, 250, steps=4)
    await pw_page.mouse.up()
    await asyncio.sleep(0.2)

    start = time.monotonic()
    await _click_send(pw_page)
    base_url, _ = bridge_server
    data = await wait_for_capture(base_url, timeout=8.0)
    elapsed = time.monotonic() - start

    # Generous ceiling — pre-fix this would hit the 30 s lib timeout, so
    # 4 s gives plenty of head-room for CI flakiness while still failing
    # loud if the eagerify path regresses.
    assert elapsed < 4.0, (
        f"Capture took {elapsed:.2f}s on a page with offscreen lazy "
        f"images — eagerifyLazyImages or timeout:2000 likely regressed. "
        f"(pre-v0.5.14 baseline: 30 s)"
    )
    assert data["mode"] == "annotate"


# ─────────────────────────────────────────────────────────────────────
# 2. Cross-origin Google Fonts CSS doesn't break capture
# ─────────────────────────────────────────────────────────────────────


async def test_webfont_page_capture_succeeds(
    pw_page, test_page_server, bridge_server, bridge_port
):
    """A page using Google Fonts via cross-origin <link> triggers a
    `SecurityError: Failed to read the 'cssRules' property` warning from
    modern-screenshot — by design, the browser blocks cross-origin
    CSSStyleSheet introspection.

    The library catches that error internally and proceeds with
    rendering. This test asserts the catch-and-continue still works:
    capture must succeed and produce a valid POST regardless of the
    warning. If a future modern-screenshot upgrade started propagating
    that error instead of swallowing it, capture would break and this
    test would catch it."""
    url = _fixture_url(test_page_server, "webfont_page.html")
    await pw_page.goto(url)
    await _inject_and_wait(pw_page, bridge_port)

    await pw_page.keyboard.press("Alt+s")  # Element mode
    await asyncio.sleep(0.3)

    el = await pw_page.query_selector("#card")
    box = await el.bounding_box()
    cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    await pw_page.mouse.move(cx, cy)
    await asyncio.sleep(0.3)
    await pw_page.mouse.click(cx, cy)
    await _click_send(pw_page)

    base_url, _ = bridge_server
    data = await wait_for_capture(base_url, timeout=5.0)
    assert data["mode"] == "element"
    selectors = [e["selector"] for e in data["elements"]]
    assert any("#card" in s for s in selectors)


# ─────────────────────────────────────────────────────────────────────
# 3. Faithful capture: JS-modified DOM survives (vs. server re-fetch)
# ─────────────────────────────────────────────────────────────────────


async def test_js_modified_dom_preserved(
    pw_page, test_page_server, bridge_server, bridge_port
):
    """The fixture renders a "logged out" state initially. JS flips it
    to "logged in" with a personalized username and a `data-session`
    attribute — none of which are present in the static HTML.

    This is the defining test of the client-side PNG path. A server-side
    Playwright re-fetch (which happens when no `pageScreenshotBase64` is
    sent) would request the URL fresh and see only the initial HTML —
    losing the JS-applied state. v0.5.14 sendCapture no longer silently
    falls back to that path on render error, so the captured DOM context
    must reflect the user's actual current state.

    We assert on the capture's `outerHTML` and `text` fields — both are
    extracted from the live DOM at the moment of capture, so the JS
    modifications must show up there."""
    url = _fixture_url(test_page_server, "js_modified_page.html")
    await pw_page.goto(url)
    await _inject_and_wait(pw_page, bridge_port)

    # Trigger the JS that flips the page into logged-in state.
    await pw_page.evaluate("logIn('alice')")
    await asyncio.sleep(0.2)

    await pw_page.keyboard.press("Alt+s")
    await asyncio.sleep(0.3)

    el = await pw_page.query_selector("#user-greeting")
    box = await el.bounding_box()
    cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    await pw_page.mouse.move(cx, cy)
    await asyncio.sleep(0.3)
    await pw_page.mouse.click(cx, cy)
    await _click_send(pw_page)

    base_url, _ = bridge_server
    data = await wait_for_capture(base_url, timeout=5.0)
    greeting_elements = [
        e for e in data["elements"] if "user-greeting" in e.get("selector", "")
    ]
    assert len(greeting_elements) > 0, "Expected #user-greeting in capture"
    el_data = greeting_elements[0]
    # The username and status text are JS-set; they must appear in the
    # captured outerHTML (faithful-capture invariant).
    assert "alice" in el_data["outerHTML"], (
        "JS-set username 'alice' missing from captured outerHTML — "
        "faithful capture regression?"
    )
    assert "logged in" in el_data["outerHTML"]
    # The data-session attribute is also JS-set.
    assert "data-session" in el_data["outerHTML"]


# ─────────────────────────────────────────────────────────────────────
# 4. Send button state machine: dim → success → hide
# ─────────────────────────────────────────────────────────────────────


async def test_send_button_state_machine(
    pw_page, test_page_server, bridge_server, bridge_port
):
    """Validates the v0.5.15 four-state Send button by sampling its DOM
    state across the capture lifecycle:

      t=0+        dim     opacity 0.7, disabled, text "Send"
      (>500 ms)   loading green ring spinner, disabled
      on success  success text "✓", disabled
      +600 ms     hidden  subpanel display:none

    On test_page.html (no images, ~10 elements) capture finishes in
    ~100-200 ms — well under the 500 ms loading-indicator delay — so the
    "loading" state is normally invisible. The test instruments via
    page.evaluate to capture state snapshots without racing the fast
    transitions; it asserts the dim → success → hidden sequence with
    moderate timing tolerance.
    """
    await pw_page.goto(test_page_server)
    await _inject_and_wait(pw_page, bridge_port)

    await pw_page.keyboard.press("Alt+s")
    await asyncio.sleep(0.3)

    el = await pw_page.query_selector("#title")
    box = await el.bounding_box()
    cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    await pw_page.mouse.move(cx, cy)
    await asyncio.sleep(0.3)
    await pw_page.mouse.click(cx, cy)

    # Capture the idle state of the button right after selection.
    idle_state = await pw_page.evaluate("""() => {
        const b = document.getElementById('__uiinsp_subtoolbar_send');
        return b ? { text: b.textContent, disabled: b.disabled, opacity: b.style.opacity } : null;
    }""")
    assert idle_state is not None
    assert idle_state["text"] == "Send"
    assert idle_state["disabled"] is False

    # Trigger Send and immediately sample the dim state. The capture is
    # async, so dim must be visible at this exact moment (set
    # synchronously before any await in sendCapture).
    await pw_page.dispatch_event("#__uiinsp_subtoolbar_send", "click")
    dim_state = await pw_page.evaluate("""() => {
        const b = document.getElementById('__uiinsp_subtoolbar_send');
        return b ? { text: b.textContent, disabled: b.disabled, opacity: b.style.opacity } : null;
    }""")
    assert dim_state is not None
    assert dim_state["disabled"] is True, "Button must be disabled in dim state"
    # Send text persists in dim — only "loading" replaces it with spinner.
    assert dim_state["text"] == "Send"
    assert dim_state["opacity"] == "0.7"

    # Wait for the success "✓" state to appear. Capture should be quick
    # on this fixture, but we poll briefly to cover CI variance.
    success_seen = False
    for _ in range(40):  # up to ~2 s
        await asyncio.sleep(0.05)
        state = await pw_page.evaluate("""() => {
            const b = document.getElementById('__uiinsp_subtoolbar_send');
            return b ? { text: b.textContent } : null;
        }""")
        if state and state["text"] == "✓":
            success_seen = True
            break
    assert success_seen, "Send button never transitioned to success state '✓'"

    # After SUCCESS_FLASH_MS (600 ms), the subpanel hides.
    await asyncio.sleep(0.8)
    hidden = await pw_page.evaluate("""() => {
        const sub = document.getElementById('__uiinsp_subtoolbar');
        return sub ? sub.style.display === 'none' : true;
    }""")
    assert hidden, "Subpanel did not hide after success flash"


# ─────────────────────────────────────────────────────────────────────
# 5. Pill stays visible throughout capture (no visibility:hidden hack)
# ─────────────────────────────────────────────────────────────────────


async def test_pill_remains_visible_during_capture(
    pw_page, test_page_server, bridge_server, bridge_port
):
    """v0.5.13 hid all `id^=__uiinsp_` elements via `visibility: hidden`
    around modern-screenshot's render call so the pill wouldn't appear in
    the screenshot. On real-world pages where capture took several
    seconds, users saw the pill flicker / vanish — the change that
    triggered the v0.5.14 work in the first place.

    v0.5.14 replaced that visibility-hide with modern-screenshot's
    `filter: (n) => !isPeekNode(n)` callback, which drops Peek elements
    at clone time so they never enter the screenshot. The original DOM
    is never mutated.

    This test polls the toolbar's computed visibility throughout the
    capture lifecycle. If any sample is "hidden", the regression has
    returned. Polling runs in the page context via page.evaluate so we
    can sample faster than Python ↔ browser round-trips allow."""
    await pw_page.goto(test_page_server)
    await _inject_and_wait(pw_page, bridge_port)

    await pw_page.keyboard.press("Alt+s")
    await asyncio.sleep(0.3)

    el = await pw_page.query_selector("#title")
    box = await el.bounding_box()
    cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    await pw_page.mouse.move(cx, cy)
    await asyncio.sleep(0.3)
    await pw_page.mouse.click(cx, cy)

    # Sample the toolbar's computed visibility every ~5 ms for 1500 ms.
    # The poll loop runs entirely in the page context to dodge
    # cross-process sampling lag; we read the result back at the end.
    visibility_samples = await pw_page.evaluate("""async () => {
        const samples = [];
        const start = performance.now();
        // Trigger Send.
        document.getElementById('__uiinsp_subtoolbar_send').click();
        // Sample for ~1500 ms.
        while (performance.now() - start < 1500) {
            const tb = document.getElementById('__uiinsp_toolbar');
            if (tb) {
                samples.push({
                    t: Math.round(performance.now() - start),
                    visibility: getComputedStyle(tb).visibility,
                    display: getComputedStyle(tb).display,
                });
            }
            await new Promise(r => setTimeout(r, 5));
        }
        return samples;
    }""")

    assert len(visibility_samples) > 50, (
        f"Sampling loop produced too few samples ({len(visibility_samples)}); "
        f"the page may have navigated or crashed."
    )
    hidden_samples = [s for s in visibility_samples if s["visibility"] != "visible"]
    assert not hidden_samples, (
        f"Toolbar became invisible during capture — visibility:hidden "
        f"regression. First offending sample: {hidden_samples[0]}"
    )


# ─────────────────────────────────────────────────────────────────────
# 6. loading="lazy" attribute is restored after capture
# ─────────────────────────────────────────────────────────────────────


async def test_lazy_loading_attribute_restored(
    pw_page, test_page_server, bridge_server, bridge_port
):
    """v0.5.14 mutates each `<img loading="lazy">` to `loading="eager"`
    during capture so the browser fetches them immediately. After
    capture completes, `restoreLazyImages` puts the original attribute
    back — leaving the user's page exactly as Peek found it.

    Without restoration, repeated captures would permanently switch
    every lazy image on the page to eager, defeating the user's
    page-level perf optimization. This test validates that all four
    icons in the lazy_images fixture have `loading="lazy"` again after
    a full capture round-trip."""
    url = _fixture_url(test_page_server, "lazy_images.html")
    await pw_page.goto(url)
    await _inject_and_wait(pw_page, bridge_port)

    # Sanity: confirm the fixture's images really do start as lazy.
    pre_loading = await pw_page.evaluate("""() => {
        return [...document.querySelectorAll('img')].map(i => i.getAttribute('loading'));
    }""")
    assert pre_loading == ["lazy", "lazy", "lazy", "lazy"]

    await pw_page.keyboard.press("Alt+a")  # Annotate captures documentElement
    await asyncio.sleep(0.3)

    await pw_page.mouse.move(150, 150)
    await pw_page.mouse.down()
    await pw_page.mouse.move(250, 200, steps=3)
    await pw_page.mouse.up()
    await asyncio.sleep(0.2)

    await _click_send(pw_page)
    base_url, _ = bridge_server
    await wait_for_capture(base_url, timeout=5.0)

    # Restoration runs in domToPng's finally block, which has already
    # completed by the time wait_for_capture returns the POST result.
    post_loading = await pw_page.evaluate("""() => {
        return [...document.querySelectorAll('img')].map(i => i.getAttribute('loading'));
    }""")
    assert post_loading == ["lazy", "lazy", "lazy", "lazy"], (
        f"loading='lazy' attributes not restored after capture: {post_loading}. "
        f"v0.5.14's restoreLazyImages may have regressed."
    )
