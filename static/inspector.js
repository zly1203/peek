/**
 * Peek — inject into any localhost page via bookmarklet.
 * Provides region select, element select, and annotation modes.
 * Sends captures to bridge server at localhost:8899.
 */
(function () {
  // Keep the version constant INSIDE the IIFE — not at script top level.
  // Top-level `const` goes into the global Script scope and persists across
  // script reloads, so re-running inspector.js after a destroy() (e.g. user
  // clicked ✕ and then re-clicked the bookmarklet) would throw
  // "already declared" and the IIFE never runs. Locally scoped means each
  // load gets a fresh binding.
  const __PEEK_INSPECTOR_VERSION = "0.5.16";

  if (window.__inspectorActive) {
    const prev = window.__inspectorVersion || "pre-0.5";
    if (prev === __PEEK_INSPECTOR_VERSION) {
      // Same version already running — nothing to do.
      return;
    }
    // Version mismatch. Prefer graceful takeover: tear down the old
    // instance in place and continue with fresh init below. Requires the
    // previously-loaded version to expose window.__peekTeardown (v0.5.5+).
    if (typeof window.__peekTeardown === "function") {
      try { window.__peekTeardown(); }
      catch (e) { console.warn(`[Peek] old teardown (${prev}) failed, reload the page:`, e); return; }
      console.info(`[Peek] Upgraded ${prev} → ${__PEEK_INSPECTOR_VERSION} in place.`);
    } else {
      console.warn(
        `[Peek] ${prev} is running but has no teardown hook. ` +
        `Reload the page to use ${__PEEK_INSPECTOR_VERSION}.`
      );
      alert(
        `Peek has been upgraded (was ${prev}, now ${__PEEK_INSPECTOR_VERSION}).\n\n` +
        `Please reload this page to use the new version.\n` +
        `From ${__PEEK_INSPECTOR_VERSION} onward, future upgrades happen automatically without a reload.`
      );
      return;
    }
  }
  window.__inspectorActive = true;
  window.__inspectorVersion = __PEEK_INSPECTOR_VERSION;

  const BRIDGE = window.__PEEK_BRIDGE_URL || "http://localhost:8899";
  const NS = "__uiinsp_"; // namespace prefix for all injected elements

  // ─── State ───
  let mode = null; // 'region' | 'select' | 'annotate' | null
  let overlay, toolbar, subtoolbar, modeTip, highlightBox, regionBox, canvas, canvasCtx;
  let regionStart = null;
  let drawing = false;
  let savedScroll = { x: 0, y: 0 }; // saved scroll position for annotate mode
  let annotateLastPos = null;
  let pendingCapture = null; // staged capture data waiting for Send
  let pendingCaptureTarget = null; // DOM element to render (kept off `pendingCapture` since DOM nodes can't JSON-serialize)

  // ─── Utility: CSS selector for element ───
  function getSelector(el) {
    if (el.id) return `#${el.id}`;
    const parts = [];
    while (el && el !== document.body && el !== document.documentElement) {
      let part = el.tagName.toLowerCase();
      if (el.id) {
        parts.unshift(`#${el.id}`);
        break;
      }
      if (el.className && typeof el.className === "string") {
        const cls = el.className.trim().split(/\s+/).filter(c => !c.startsWith(NS)).slice(0, 3).join(".");
        if (cls) part += `.${cls}`;
      }
      // nth-child for disambiguation
      const parent = el.parentElement;
      if (parent) {
        const siblings = Array.from(parent.children).filter(c => c.tagName === el.tagName);
        if (siblings.length > 1) {
          const idx = siblings.indexOf(el) + 1;
          part += `:nth-child(${idx})`;
        }
      }
      parts.unshift(part);
      el = el.parentElement;
    }
    return parts.join(" > ");
  }

  // ─── Utility: get computed styles ───
  function getKeyStyles(el) {
    const cs = getComputedStyle(el);
    return {
      width: cs.width, height: cs.height,
      fontSize: cs.fontSize, fontFamily: cs.fontFamily,
      color: cs.color, backgroundColor: cs.backgroundColor,
      padding: cs.padding, margin: cs.margin,
      display: cs.display, position: cs.position,
      overflow: cs.overflow,
    };
  }

  // ─── Utility: short element descriptor for ancestor chain ───
  function describeEl(el) {
    let s = el.tagName.toLowerCase();
    if (el.id) return s + "#" + el.id;
    if (el.className && typeof el.className === "string") {
      const cls = el.className.trim().split(/\s+/).filter(c => !c.startsWith(NS)).slice(0, 2).join(".");
      if (cls) s += "." + cls;
    }
    return s;
  }

  // ─── Utility: bounded heading text extraction (max 80 chars, no full subtree alloc) ───
  function safeHeadingText(headingEl) {
    let out = "";
    const MAX = 80;
    // Walk text nodes only, accumulate up to MAX chars (avoids huge .textContent allocation)
    const walker = document.createTreeWalker(headingEl, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode()) && out.length < MAX) {
      const v = node.nodeValue || "";
      // Take only what we still need to avoid copying massive text nodes
      out += v.length > MAX - out.length ? v.slice(0, MAX - out.length) : v;
    }
    return out.trim().slice(0, MAX);
  }

  // ─── Utility: get DOM structural context ───
  function getDOMContext(el) {
    // Ancestor chain (up to 5 levels)
    const ancestors = [];
    let cur = el.parentElement;
    let depth = 0;
    while (cur && cur !== document.documentElement && depth < 5) {
      ancestors.unshift(describeEl(cur));
      cur = cur.parentElement;
      depth++;
    }

    // Sibling position (cap children scan at 200 to bound work on huge parents)
    let siblingPosition = null;
    const parent = el.parentElement;
    if (parent) {
      const totalChildren = parent.children.length;
      if (totalChildren > 200) {
        siblingPosition = "child of large parent (" + totalChildren + " siblings)";
      } else {
        const sameTag = Array.from(parent.children).filter(c => c.tagName === el.tagName);
        if (sameTag.length > 1) {
          siblingPosition = (sameTag.indexOf(el) + 1) + " of " + sameTag.length + " <" + el.tagName.toLowerCase() + "> siblings";
        } else {
          const idx = Array.from(parent.children).indexOf(el) + 1;
          siblingPosition = "child " + idx + " of " + totalChildren;
        }
      }
    }

    // Nearest heading — bounded walk: max 50 sibling scans, max 10 levels up
    let nearestHeading = null;
    cur = el;
    let levelsWalked = 0;
    let totalSibsScanned = 0;
    const MAX_SIBS = 50;
    const MAX_LEVELS = 10;

    outer: while (cur && cur !== document.body && levelsWalked < MAX_LEVELS) {
      let sib = cur.previousElementSibling;
      let sibCount = 0;
      while (sib && totalSibsScanned < MAX_SIBS) {
        if (/^H[1-6]$/.test(sib.tagName)) {
          nearestHeading = sib.tagName.toLowerCase() + ": " + safeHeadingText(sib);
          break outer;
        }
        // Use querySelector but only on small subtrees (skip if sibling has many descendants)
        if (sib.children.length < 100 && sib.querySelector) {
          const innerH = sib.querySelector("h1, h2, h3, h4, h5, h6");
          if (innerH) {
            nearestHeading = innerH.tagName.toLowerCase() + ": " + safeHeadingText(innerH);
            break outer;
          }
        }
        sib = sib.previousElementSibling;
        sibCount++;
        totalSibsScanned++;
      }
      cur = cur.parentElement;
      levelsWalked++;
    }

    // Parent layout
    let parentLayout = null;
    if (parent) {
      const pcs = getComputedStyle(parent);
      const display = pcs.display;
      if (display.includes("flex")) {
        parentLayout = "flex, " + pcs.flexDirection;
      } else if (display.includes("grid")) {
        parentLayout = "grid";
      } else if (display) {
        parentLayout = display;
      }
    }

    // Child count (helps know if element is a container or leaf)
    const childCount = el.children.length;

    return {
      ancestor_chain: ancestors,
      sibling_position: siblingPosition,
      nearest_heading: nearestHeading,
      parent_layout: parentLayout,
      child_count: childCount,
    };
  }

  // ─── Utility: safe URL (strip query params to avoid leaking tokens) ───
  function safeUrl() {
    return location.origin + location.pathname;
  }

  // ─── Utility: sanitize outerHTML (redact sensitive form values) ───
  function sanitizeOuterHTML(el) {
    const clone = el.cloneNode(true);
    clone.querySelectorAll('input[type="password"]').forEach(inp => inp.removeAttribute("value"));
    clone.querySelectorAll('input[type="hidden"]').forEach(inp => inp.setAttribute("value", "[REDACTED]"));
    return clone.outerHTML.slice(0, 2000);
  }

  // ─── Smallest DOM ancestor whose bounding box fully contains a viewport rect.
  // Used by Region mode to pick a tight render target instead of walking the
  // entire documentElement. If no ancestor contains the rect (unusual — would
  // mean the user dragged outside any positioned element), we fall back to
  // body so the caller still gets a valid target.
  function smallestContainerOfRect(rect) {
    const cx = rect.x + rect.width / 2;
    const cy = rect.y + rect.height / 2;
    overlay && (overlay.style.pointerEvents = "none");
    let el = document.elementFromPoint(cx, cy);
    overlay && (overlay.style.pointerEvents = "");
    if (!el || isPeekNode(el) || el.closest(`[id^="${NS}"]`)) {
      return document.body;
    }
    while (el && el !== document.body && el !== document.documentElement) {
      const r = el.getBoundingClientRect();
      if (
        r.left <= rect.x &&
        r.top <= rect.y &&
        r.right >= rect.x + rect.width &&
        r.bottom >= rect.y + rect.height
      ) {
        return el;
      }
      el = el.parentElement;
    }
    return document.body;
  }

  // ─── Utility: get elements in a rect ───
  function getElementsInRect(rect) {
    const results = [];
    const all = document.querySelectorAll("body *");
    for (const el of all) {
      if (el.closest(`[id^="${NS}"]`) || el.id?.startsWith(NS)) continue;
      const r = el.getBoundingClientRect();
      if (r.width < 5 || r.height < 5) continue;
      // skip SVG internals (Plotly drag handles, grid lines, etc.)
      const tag = el.tagName.toLowerCase();
      // SVG elements have SVGAnimatedString for className — use getAttribute instead
      const cls = el.getAttribute?.("class") || "";
      if (["path", "rect", "line", "circle", "clippath", "defs"].includes(tag) && el.closest(".plotly")) continue;
      if (cls.match(/drag|crisp|ygrid|xgrid|gridlayer|zerolinelayer|bglayer|draglayer|overplot|cartesianlayer|plot-container|svg-container/)) continue;
      // skip deep Plotly SVG internals (trace, points, bars inner groups)
      if (["g"].includes(tag) && el.closest(".plotly") && cls.match(/^(trace|points?|bars|barlayer|mlayer|xy|scatter)$/)) continue;
      // check intersection
      if (r.right >= rect.x && r.left <= rect.x + rect.width &&
          r.bottom >= rect.y && r.top <= rect.y + rect.height) {
        // only leaf-ish elements (no more than 5 children)
        if (el.children.length <= 5) {
          results.push({
            selector: getSelector(el),
            tagName: tag,
            classes: Array.from(el.classList || []).filter(c => !c.startsWith(NS)),
            id: el.id || "",
            text: (el.textContent || "").trim().slice(0, 200),
            boundingBox: { x: Math.round(r.x), y: Math.round(r.y), width: Math.round(r.width), height: Math.round(r.height) },
            styles: getKeyStyles(el),
          });
        }
      }
    }
    return results.slice(0, 20); // cap
  }

  // ─── Faithful page PNG (via modern-screenshot, MIT) ───
  let modernScreenshotLoadPromise = null;
  function ensureModernScreenshotLoaded() {
    if (window.modernScreenshot && window.modernScreenshot.domToPng) return Promise.resolve();
    if (modernScreenshotLoadPromise) return modernScreenshotLoadPromise;
    modernScreenshotLoadPromise = new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.src = `${BRIDGE}/static/modern-screenshot.js?t=${Date.now()}`;
      s.onload = () => resolve();
      s.onerror = () => {
        modernScreenshotLoadPromise = null;
        reject(new Error("Failed to load modern-screenshot"));
      };
      document.head.appendChild(s);
    });
    return modernScreenshotLoadPromise;
  }

  // Skip Peek's own elements during DOM cloning so they never enter the
  // screenshot — replaces the old visibility:hidden trick (which caused
  // the pill to flicker on slow captures).
  function isPeekNode(node) {
    if (!node || node.nodeType !== 1) return false;
    if (typeof node.id === "string" && node.id.startsWith(NS)) return true;
    if (node.classList) {
      for (const c of node.classList) if (c.startsWith(NS)) return true;
    }
    return false;
  }

  // `target` controls what subtree gets rendered:
  //   - documentElement → full viewport (annotate mode; user drew on the
  //     whole page, so we need the whole page as backdrop)
  //   - any other element → that element's subtree only (Element/Region
  //     modes; user explicitly picked it, no need to walk unrelated DOM)
  // Passing a small subtree is the real speedup vs. v0.5.13: modern-screenshot
  // walks every node it's given and inlines every <img>/font/css resource,
  // so cutting tree size cuts work proportionally.
  // Toggle verbose timing in DevTools console:
  //   localStorage.setItem('__uiinsp_debug', '1')   → on
  //   localStorage.removeItem('__uiinsp_debug')     → off
  // Off by default so production users don't see noise.
  function isDebugOn() {
    try { return localStorage.getItem(NS + "debug") === "1"; } catch { return false; }
  }

  // Force lazy-loaded images in the capture target to start fetching now,
  // so modern-screenshot's "wait until load" phase doesn't sit on them.
  // Without this, an offscreen `loading="lazy"` <img> never fires `load`
  // (the browser hasn't fetched it yet), so modern-screenshot times out
  // at its default 30 s — observed on liying.github.io's hobby icons.
  // Setting `loading="eager"` triggers an immediate fetch; combined with
  // the `timeout: 1500` we pass to domToPng, the worst case is bounded
  // to 1.5 s instead of 30 s, and small icons typically load in <300 ms.
  //
  // Returns an array of {img, originalLoading} so the caller can restore
  // the user's original `loading` attribute after capture — mutating
  // user pages without restoring is a leaky side effect.
  function eagerifyLazyImages(target) {
    const root = target === document.documentElement ? document : target;
    if (!root.querySelectorAll) return [];
    const restored = [];
    for (const img of root.querySelectorAll('img[loading="lazy"]')) {
      restored.push({ img, originalLoading: img.loading });
      img.loading = "eager";
    }
    return restored;
  }
  function restoreLazyImages(restored) {
    for (const { img, originalLoading } of restored) {
      // Once an image has finished loading, the loading attribute has no
      // further effect — but we still set it back so the page DOM looks
      // exactly like Peek never touched it.
      img.loading = originalLoading;
    }
  }

  async function capturePng(target) {
    const debug = isDebugOn();
    const tLabel = `[Peek] capturePng (${target === document.documentElement ? "full-doc" : (target.tagName?.toLowerCase() || "?")}, ${target.querySelectorAll?.("*").length ?? 0} descendants)`;
    if (debug) console.time(tLabel);
    try {
      if (debug) console.time("[Peek]   ensureModernScreenshotLoaded");
      await ensureModernScreenshotLoaded();
      if (debug) console.timeEnd("[Peek]   ensureModernScreenshotLoaded");

      const lazyState = eagerifyLazyImages(target);

      const isFullDoc = target === document.documentElement;
      const opts = {
        scale: 1,
        filter: (node) => !isPeekNode(node),
        // 2 s ceiling on the "wait until load" phase. Default is 30 s;
        // a single broken or unfetched <img> blocks the whole capture
        // until the timer fires. 2 s is the Doherty-threshold sweet
        // spot — short enough that users with the spinner showing don't
        // feel stuck, long enough to catch large hero images on slower
        // connections (1.5 s would cut off ~1-3 MB photos that legitimately
        // would have rendered). After timeout the image is omitted and
        // rendering continues.
        timeout: 2000,
        // When debug is on, modern-screenshot prints its own internal phase
        // timings (clone node / image to canvas / wait until load) prefixed
        // with `[modern-screenshot]`. Combined with our own labels below,
        // this gives a complete picture of where time actually goes — the
        // first thing to look at when capture feels slow.
        debug,
      };
      if (isFullDoc) {
        // Same viewport-clip trick as v0.5.13 — output is sized to viewport
        // and the cloned DOM is translated so the visible area lands at (0,0).
        opts.width = window.innerWidth;
        opts.height = window.innerHeight;
        opts.style = {
          transform: `translate(${-window.scrollX}px, ${-window.scrollY}px)`,
          transformOrigin: "top left",
        };
      }
      // For non-full-doc targets, leave width/height unset — modern-screenshot
      // sizes the output to target.getBoundingClientRect() automatically.

      let dataUrl;
      try {
        if (debug) console.time("[Peek]   domToPng");
        dataUrl = await window.modernScreenshot.domToPng(target, opts);
        if (debug) console.timeEnd("[Peek]   domToPng");
      } finally {
        // Restore lazy loading state whether capture succeeded or threw,
        // so the user's page DOM is left exactly as Peek found it.
        restoreLazyImages(lazyState);
      }

      const comma = dataUrl.indexOf(",");
      return comma >= 0 ? dataUrl.slice(comma + 1) : dataUrl;
    } finally {
      if (debug) console.timeEnd(tLabel);
    }
  }

  // ─── Send capture to bridge ───
  // `target` is the element to rasterize — Element/Region pass the picked
  // element / smallest containing ancestor; annotate passes documentElement.
  // Without a faithful client-side PNG the server falls back to Playwright,
  // which re-fetches the URL and loses logged-in/JS-modified state — so we
  // don't silently swallow render errors here, we surface them.
  //
  // Button state choreography (see setSendBtnState):
  //   click → "dim" (instant ack, before any await)
  //          → at +500ms, if still in flight → "loading" (spinner)
  //          → on success → "success" ("✓"), caller hides subpanel after
  //                          SUCCESS_FLASH_MS
  //          → on any failure → "idle" (back to clickable, hint updated
  //                              by caller)
  // The bottom-center "Captured!" toast was removed: focal-point button
  // confirmation is harder to miss than a far-away toast. Error toasts
  // stay (red, must-not-miss).
  async function sendCapture(data, target) {
    setSendBtnState("dim");
    let loadingTimer = setTimeout(() => {
      setSendBtnState("loading");
      loadingTimer = null;
    }, LOADING_INDICATOR_DELAY_MS);
    const cancelLoadingTimer = () => {
      if (loadingTimer) { clearTimeout(loadingTimer); loadingTimer = null; }
    };

    try {
      const png = await capturePng(target || document.documentElement);
      if (png) data.pageScreenshotBase64 = png;
    } catch (e) {
      cancelLoadingTimer();
      setSendBtnState("idle");
      console.error("[Peek] client-side PNG failed:", e);
      showToast("Peek: screenshot failed — try again or pick a smaller selection.", true);
      return;
    }

    let resp;
    try {
      resp = await fetch(`${BRIDGE}/api/capture`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      });
    } catch (e) {
      cancelLoadingTimer();
      setSendBtnState("idle");
      // True network-level failure: bridge really isn't reachable.
      showToast(
        "Peek bridge not running — open Claude Code (it starts peek automatically) or run `peek mcp` in a terminal.",
        true,
      );
      console.error("[Peek] capture fetch failed:", e);
      return;
    }

    // Bridge responded but with an error (413 too-large, 500 server bug, etc.).
    // Don't mis-report as "bridge not running" — show what the server said.
    if (!resp.ok) {
      cancelLoadingTimer();
      setSendBtnState("idle");
      let detail = `HTTP ${resp.status}`;
      try {
        const body = await resp.json();
        detail = body.error || body.warning || body.detail || detail;
      } catch {}
      if (resp.status === 413) {
        showToast(
          `Peek: capture too large (${detail}). Try a shorter page or a smaller region.`,
          true,
        );
      } else {
        showToast(`Peek capture failed: ${detail}`, true);
      }
      console.error("[Peek] capture rejected by bridge:", resp.status, detail);
      return;
    }

    try {
      const result = await resp.json();
      cancelLoadingTimer();
      setSendBtnState("success");
      return result;
    } catch (e) {
      cancelLoadingTimer();
      setSendBtnState("idle");
      // 2xx response but body isn't JSON — unusual but possible (proxy etc.).
      showToast("Peek: unexpected response from bridge.", true);
      console.error("[Peek] response parse failed:", e);
    }
  }

  // ─── Toast notification ───
  function showToast(msg, isError = false) {
    const t = document.createElement("div");
    t.id = NS + "toast";
    Object.assign(t.style, {
      position: "fixed", bottom: "24px", left: "50%", transform: "translateX(-50%)",
      padding: "10px 24px", borderRadius: "8px", zIndex: "2147483647",
      background: isError ? "#ef4444" : "#22c55e", color: "white",
      fontSize: "14px", fontFamily: "-apple-system, system-ui, sans-serif",
      boxShadow: "0 4px 12px rgba(0,0,0,0.3)", transition: "opacity 0.3s",
    });
    t.textContent = msg;
    document.body.appendChild(t);
    setTimeout(() => { t.style.opacity = "0"; setTimeout(() => t.remove(), 300); }, 1500);
  }

  // ─── Create toolbar ───
  // ─── Load / save toolbar position ───
  const TOOLBAR_POS_KEY = NS + "toolbar_pos";
  function loadToolbarPos() {
    try {
      const raw = localStorage.getItem(TOOLBAR_POS_KEY);
      if (!raw) return null;
      const p = JSON.parse(raw);
      if (typeof p.left !== "number" || typeof p.top !== "number") return null;
      return p;
    } catch { return null; }
  }
  function saveToolbarPos(left, top) {
    try { localStorage.setItem(TOOLBAR_POS_KEY, JSON.stringify({ left, top })); } catch {}
  }

  // ─── Sub-panel below the pill — hosts Send (+ optional hint) for every
  // mode, so Send's position is consistent whether you're annotating,
  // region-selecting, or element-picking. Content is repopulated by
  // `showSubpanel(...)` when the mode / selection changes.
  function createSubpanel() {
    subtoolbar = document.createElement("div");
    subtoolbar.id = NS + "subtoolbar";
    Object.assign(subtoolbar.style, {
      position: "absolute",
      left: "0",
      top: "calc(100% + 4px)",
      display: "none",
      gap: "8px",
      alignItems: "center",
      background: "rgba(15, 23, 42, 0.85)",
      backdropFilter: "blur(8px)",
      borderRadius: "20px",
      padding: "4px 10px",
      boxShadow: "0 4px 16px rgba(0,0,0,0.25)",
      border: "1px solid rgba(255,255,255,0.1)",
      whiteSpace: "nowrap",
    });
  }

  function showSubpanel({ hintText, onSend }) {
    if (!subtoolbar) return;
    subtoolbar.innerHTML = "";

    if (hintText) {
      const hint = document.createElement("span");
      hint.id = NS + "subtoolbar_hint";
      Object.assign(hint.style, {
        color: "rgba(255,255,255,0.65)", fontSize: "12px",
        fontFamily: "-apple-system, system-ui, sans-serif",
      });
      hint.textContent = hintText;
      subtoolbar.appendChild(hint);
    }

    const sendBtn = document.createElement("button");
    sendBtn.id = NS + "subtoolbar_send";
    sendBtn.textContent = "Send";
    Object.assign(sendBtn.style, {
      // minWidth/minHeight + border-box together keep the button — and
      // the subpanel that hugs it — at a constant size in all three
      // states (Send, Capturing, hidden). The spinner is shorter than
      // a line of text, so without minHeight the button (and panel)
      // would shrink ~4px when entering Capturing.
      boxSizing: "border-box",
      padding: "4px 14px", minWidth: "56px", minHeight: "24px",
      border: "none", borderRadius: "14px",
      color: "white", fontSize: "12px", lineHeight: "16px", cursor: "pointer",
      background: "#22c55e",
      display: "inline-flex", alignItems: "center", justifyContent: "center",
    });
    sendBtn.addEventListener("click", onSend);
    subtoolbar.appendChild(sendBtn);

    subtoolbar.style.display = "flex";
    positionSubpanel();
    // Subpanel just appeared; bump modeTip down so it doesn't stack under
    // the pill in the same slot.
    positionModeTip();
  }

  function updateSubpanelHint(hintText) {
    const hint = document.getElementById(NS + "subtoolbar_hint");
    if (hint) hint.textContent = hintText;
  }

  // ─── Send button state machine ────────────────────────────────────────
  // Four states span the full click→capture→done UX:
  //   "idle"     green "Send", enabled — default, accepts clicks
  //   "dim"      green "Send", disabled, opacity 0.7 — instant click ack
  //   "loading"  green ring spinner, disabled — only shown if capture
  //              still running 500ms after click (delayed-loading pattern)
  //   "success"  green "✓", enabled-look but disabled — shown briefly
  //              before the subpanel auto-hides
  //
  // Why four and not just two: the typical 400-500ms capture finishes
  // before "loading" would appear, so without "dim" + "success" the
  // button would never visually change on fast paths and users would
  // wonder if their click registered. "dim" gives instant feedback;
  // "success" gives a clear focal-point confirmation right where the
  // user is already looking (replaces the easy-to-miss bottom toast).
  const LOADING_INDICATOR_DELAY_MS = 500;
  const SUCCESS_FLASH_MS = 600;

  function setSendBtnState(state) {
    const btn = document.getElementById(NS + "subtoolbar_send");
    if (!btn) return;
    // Always start from a clean slate so transitions don't accumulate
    // stale child nodes (e.g. an old spinner sitting next to "✓").
    btn.textContent = "";
    if (state === "idle") {
      btn.disabled = false;
      btn.style.opacity = "1";
      btn.style.cursor = "pointer";
      btn.textContent = "Send";
      return;
    }
    if (state === "dim") {
      btn.disabled = true;
      btn.style.opacity = "0.7";
      btn.style.cursor = "default";
      btn.textContent = "Send";
      return;
    }
    if (state === "loading") {
      btn.disabled = true;
      btn.style.opacity = "0.92";
      btn.style.cursor = "default";
      // CSS ring spinner — rotates a partial-border circle. Cleaner than
      // a Unicode glyph (which depends on font glyph-box centering and
      // can wobble) and stays compact: only ~12px wide, fits inside the
      // pre-reserved Send-button width without changing the layout.
      const spinner = document.createElement("span");
      spinner.id = NS + "spinner";
      Object.assign(spinner.style, {
        display: "inline-block",
        width: "12px", height: "12px",
        border: "2px solid rgba(255,255,255,0.35)",
        borderTopColor: "white",
        borderRadius: "50%",
        animation: NS + "spin 0.7s linear infinite",
      });
      btn.appendChild(spinner);
      ensureSpinnerKeyframes();
      return;
    }
    if (state === "success") {
      btn.disabled = true;
      btn.style.opacity = "1";
      btn.style.cursor = "default";
      btn.textContent = "✓";
      return;
    }
  }

  let spinnerKeyframesInjected = false;
  function ensureSpinnerKeyframes() {
    if (spinnerKeyframesInjected) return;
    const style = document.createElement("style");
    style.id = NS + "spinner_kf";
    style.textContent = `@keyframes ${NS}spin{to{transform:rotate(360deg)}}`;
    document.head.appendChild(style);
    spinnerKeyframesInjected = true;
  }

  function hideSubpanel() {
    if (subtoolbar) subtoolbar.style.display = "none";
    // Subpanel gone; let modeTip reclaim the slot right below the pill.
    positionModeTip();
  }

  // ─── Mode hint: tiny caption under the pill while a mode is active ───
  // Just enough to remind users Esc bails out — easy to forget once you've
  // committed to a selection and realised you wanted to scroll or undo.
  function createModeTip() {
    modeTip = document.createElement("div");
    modeTip.id = NS + "mode_tip";
    Object.assign(modeTip.style, {
      position: "absolute",
      display: "none",
      // Match subpanel's left-edge alignment with the pill so everything
      // stacks in a single clean column below the toolbar.
      left: "0",
      whiteSpace: "nowrap",
      padding: "2px 10px",
      background: "rgba(15, 23, 42, 0.7)",
      color: "rgba(255, 255, 255, 0.6)",
      fontSize: "10.5px",
      fontFamily: "-apple-system, system-ui, sans-serif",
      borderRadius: "10px",
      pointerEvents: "none",
      userSelect: "none",
      letterSpacing: "0.2px",
    });
  }

  function updateModeTip() {
    if (!modeTip) return;
    const messages = {
      region: "Drag to select  ·  Esc to cancel",
      select: "Click an element  ·  Esc to cancel",
      annotate: "Draw, then Send  ·  Esc to cancel",
    };
    const msg = messages[mode];
    if (!msg) { modeTip.style.display = "none"; return; }
    modeTip.textContent = msg;
    modeTip.style.display = "block";
    positionModeTip();
  }

  // Whether the subpanel is currently right-anchored to the toolbar
  // (vs. the default left-anchor). Read-only signal for positionModeTip
  // to mirror the same anchor and keep the visual column aligned.
  function subpanelIsRightAnchored() {
    if (!subtoolbar) return false;
    return subtoolbar.style.left === "auto";
  }

  function positionModeTip() {
    if (!modeTip || modeTip.style.display === "none") return;
    // Stack below the subpanel when the subpanel is below the pill;
    // above the subpanel when the subpanel flipped above. 4px gap matches
    // the subpanel's gap to the pill — keeps the entire pill / subpanel
    // / modeTip stack on one consistent thin-rule rhythm.
    const subVisible = subtoolbar && subtoolbar.style.display !== "none";
    if (subVisible) {
      const subBelow = subtoolbar.style.top !== "auto" && subtoolbar.style.top !== "";
      const subH = subtoolbar.offsetHeight || 32;
      if (subBelow) {
        modeTip.style.top = `calc(100% + 4px + ${subH}px + 4px)`;
        modeTip.style.bottom = "auto";
      } else {
        modeTip.style.bottom = `calc(100% + 4px + ${subH}px + 4px)`;
        modeTip.style.top = "auto";
      }
      // Mirror subpanel's horizontal anchor — if the subpanel flipped
      // right because of viewport overflow, modeTip should too, otherwise
      // they'd separate into two visually-disconnected columns.
      if (subpanelIsRightAnchored()) {
        modeTip.style.left = "auto";
        modeTip.style.right = "0";
      } else {
        modeTip.style.right = "auto";
        modeTip.style.left = "0";
      }
    } else {
      // Subpanel hidden — modeTip alone, sits right under the pill.
      // Re-evaluate horizontal anchor from scratch since the modeTip
      // itself can also overflow on a far-right toolbar (rare — modeTip
      // is shorter than subpanel — but cheap to handle for symmetry).
      modeTip.style.top = "calc(100% + 4px)";
      modeTip.style.bottom = "auto";
      modeTip.style.left = "0";
      modeTip.style.right = "auto";
      const tipRect = modeTip.getBoundingClientRect();
      if (tipRect.right > window.innerWidth - 4) {
        modeTip.style.left = "auto";
        modeTip.style.right = "0";
      }
    }
  }

  // Position the sub-panel relative to the pill, flipping vertically
  // (top↔bottom) if there's no room below, and horizontally (left↔right)
  // if the panel would extend past the viewport's right edge.
  //
  // The horizontal flip matters because the subpanel's content (long
  // element-mode hints like "Element: <div#some-long-id> — click another
  // to change") is often wider than the toolbar itself. With the default
  // top-right toolbar position (right: 16px) and a left-anchored subpanel,
  // the subpanel's right edge could end up tens of pixels past the
  // viewport, putting the Send button partially or fully off-screen.
  function positionSubpanel() {
    if (!subtoolbar || subtoolbar.style.display === "none") return;
    const pillRect = toolbar.getBoundingClientRect();
    const subH = subtoolbar.offsetHeight || 36;

    // Vertical flip — flip above the pill if there's no room below.
    const spaceBelow = window.innerHeight - pillRect.bottom;
    if (spaceBelow < subH + 12) {
      subtoolbar.style.top = "auto";
      subtoolbar.style.bottom = "calc(100% + 4px)";
    } else {
      subtoolbar.style.bottom = "auto";
      subtoolbar.style.top = "calc(100% + 4px)";
    }

    // Horizontal flip — start by resetting to the default left-anchor so
    // we measure the natural layout, never a stale right-anchored one
    // from a prior call. Then check if the right edge spills past the
    // viewport; if so, flip to right-anchor (subpanel grows leftward
    // from the toolbar's right edge instead of rightward from its left).
    subtoolbar.style.left = "0";
    subtoolbar.style.right = "auto";
    const subRect = subtoolbar.getBoundingClientRect();
    if (subRect.right > window.innerWidth - 4) {
      subtoolbar.style.left = "auto";
      subtoolbar.style.right = "0";
    }
  }

  function createToolbar() {
    toolbar = document.createElement("div");
    toolbar.id = NS + "toolbar";
    const saved = loadToolbarPos();
    // Default: top-right corner, 16px margin
    const initial = saved || { left: null, top: 16 };

    Object.assign(toolbar.style, {
      position: "fixed",
      top: initial.top + "px",
      ...(initial.left !== null
        ? { left: initial.left + "px" }
        : { right: "16px" }),
      background: "rgba(15, 23, 42, 0.85)",
      backdropFilter: "blur(8px)",
      borderRadius: "24px",
      padding: "4px 6px",
      display: "flex", alignItems: "center", gap: "2px",
      zIndex: "2147483646",
      fontFamily: "-apple-system, system-ui, sans-serif",
      boxShadow: "0 4px 16px rgba(0,0,0,0.25)",
      border: "1px solid rgba(255,255,255,0.1)",
      userSelect: "none",
    });

    // Drag handle
    const dragHandle = document.createElement("div");
    dragHandle.textContent = "⋮⋮";
    dragHandle.title = "Drag to move";
    Object.assign(dragHandle.style, {
      cursor: "grab", padding: "6px 4px", color: "rgba(255,255,255,0.45)",
      fontSize: "13px", lineHeight: "1", letterSpacing: "-3px",
    });

    const btnStyle = {
      padding: "5px 12px", border: "none", borderRadius: "16px",
      color: "white", fontSize: "13px", cursor: "pointer",
      background: "rgba(255,255,255,0.08)", transition: "background 0.15s",
    };

    function makeBtn(label, shortcut, modeName, onClick) {
      const btn = document.createElement("button");
      btn.textContent = label;
      btn.title = `${label} (${shortcut})`;
      btn.dataset.mode = modeName;
      Object.assign(btn.style, btnStyle);
      btn.addEventListener("click", onClick);
      btn.addEventListener("mouseenter", () => { if (btn.dataset.mode !== mode) btn.style.background = "rgba(255,255,255,0.18)"; });
      btn.addEventListener("mouseleave", () => { if (btn.dataset.mode !== mode) btn.style.background = "rgba(255,255,255,0.08)"; });
      return btn;
    }

    const annotateBtn = makeBtn("Annotate", "Alt+A", "annotate", () => setMode("annotate"));
    const regionBtn = makeBtn("Region", "Alt+R", "region", () => setMode("region"));
    const selectBtn = makeBtn("Element", "Alt+S", "select", () => setMode("select"));

    const closeBtn = document.createElement("button");
    closeBtn.textContent = "✕";
    closeBtn.title = "Close Peek";
    Object.assign(closeBtn.style, { ...btnStyle, marginLeft: "4px", color: "#f87171", padding: "5px 10px" });
    closeBtn.addEventListener("click", destroy);

    toolbar.append(dragHandle, annotateBtn, regionBtn, selectBtn, closeBtn);

    // Sub-panel — attached to the toolbar so it moves with it. Populated
    // per-mode by `showSubpanel(...)`.
    createSubpanel();
    toolbar.appendChild(subtoolbar);

    // Mode tip — tiny caption below the pill while a mode is active.
    createModeTip();
    toolbar.appendChild(modeTip);

    // Keep the user's page-level popovers / dropdowns / collapsibles open
    // while they interact with Peek. Two protections:
    //   - preventDefault on mousedown: buttons never receive focus, so the
    //     page's currently-focused element (the popover trigger) does not
    //     emit blur → nothing auto-dismisses on focus loss.
    //   - stopPropagation on click: document-level "click outside to close"
    //     handlers on the page never see clicks that land on our toolbar.
    // The drag handle has its own mousedown listener that calls
    // stopPropagation, so toolbar's bubble-phase listener below is a no-op
    // when the user grabs the handle.
    //
    // Capture-phase preventDefault on document: runs before the button takes
    // focus, so the page's currently-focused element (popover trigger etc.)
    // does not blur — preserves popovers that dismiss on focus loss. We
    // intentionally do NOT stopPropagation in capture phase because that
    // would kill our own button click handlers before they run.
    //
    // Only hook `mousedown`, not `pointerdown`: preventDefault on a
    // pointerdown suppresses the follow-up compat mousedown per the
    // Pointer Events spec, which breaks our drag-handle listener (target
    // phase mousedown never fires → dragState never gets set).
    const captureGuard = (e) => {
      if (toolbar && toolbar.contains(e.target)) e.preventDefault();
    };
    document.addEventListener("mousedown", captureGuard, true);

    toolbar.addEventListener("mousedown", (e) => {
      e.preventDefault();
      e.stopPropagation();
    });
    toolbar.addEventListener("click", (e) => { e.stopPropagation(); });

    toolbar.__captureBlocker = () => {
      document.removeEventListener("mousedown", captureGuard, true);
    };

    document.body.appendChild(toolbar);

    // Drag behavior
    let dragState = null;
    dragHandle.addEventListener("mousedown", (e) => {
      const rect = toolbar.getBoundingClientRect();
      dragState = { startX: e.clientX, startY: e.clientY, origLeft: rect.left, origTop: rect.top };
      dragHandle.style.cursor = "grabbing";
      e.preventDefault();
      e.stopPropagation();
    });
    function onDragMove(e) {
      if (!dragState) return;
      const rect = toolbar.getBoundingClientRect();
      let newLeft = dragState.origLeft + (e.clientX - dragState.startX);
      let newTop = dragState.origTop + (e.clientY - dragState.startY);
      // Clamp within viewport (leave at least 8px visible edge)
      newLeft = Math.max(0, Math.min(window.innerWidth - rect.width, newLeft));
      newTop = Math.max(0, Math.min(window.innerHeight - rect.height, newTop));
      toolbar.style.left = newLeft + "px";
      toolbar.style.top = newTop + "px";
      toolbar.style.right = "auto";
      // Keep sub-panel + mode tip on the visible side of the pill while dragging
      positionSubpanel();
      positionModeTip();
      e.preventDefault();
    }
    function onDragEnd() {
      if (!dragState) return;
      dragState = null;
      dragHandle.style.cursor = "grab";
      const rect = toolbar.getBoundingClientRect();
      saveToolbarPos(Math.round(rect.left), Math.round(rect.top));
    }
    document.addEventListener("mousemove", onDragMove, true);
    document.addEventListener("mouseup", onDragEnd, true);
    // Store teardown hooks so destroy() can remove listeners
    toolbar.__dragTeardown = () => {
      document.removeEventListener("mousemove", onDragMove, true);
      document.removeEventListener("mouseup", onDragEnd, true);
    };
  }

  // ─── Create overlay (used for region + select modes) ───
  // Stop mouse events on Peek-owned full-viewport surfaces from reaching
  // the page's document-level "click outside to close" dismissers. Without
  // this, dragging on the overlay (Region mode) or drawing on the canvas
  // (Annotate mode) would collapse popovers / expanders that happen to sit
  // under the stroke.
  function isolateEvents(el) {
    const stop = (e) => e.stopPropagation();
    ["mousedown", "click", "pointerdown"].forEach(evt =>
      el.addEventListener(evt, stop)
    );
  }

  function createOverlay() {
    overlay = document.createElement("div");
    overlay.id = NS + "overlay";
    Object.assign(overlay.style, {
      position: "fixed", top: "0", left: "0", right: "0", bottom: "0",
      zIndex: "2147483645", cursor: "default",
    });
    isolateEvents(overlay);
    document.body.appendChild(overlay);
  }

  // ─── Create highlight box (element select mode) ───
  function createHighlightBox() {
    highlightBox = document.createElement("div");
    highlightBox.id = NS + "highlight";
    Object.assign(highlightBox.style, {
      position: "fixed", border: "2px solid #3b82f6", backgroundColor: "rgba(59,130,246,0.08)",
      borderRadius: "2px", pointerEvents: "none", zIndex: "2147483644",
      display: "none", transition: "all 0.05s ease-out",
    });
    document.body.appendChild(highlightBox);
  }

  // ─── Create region selection box ───
  function createRegionBox() {
    regionBox = document.createElement("div");
    regionBox.id = NS + "region";
    Object.assign(regionBox.style, {
      position: "fixed", border: "2px dashed #3b82f6", backgroundColor: "rgba(59,130,246,0.12)",
      borderRadius: "2px", pointerEvents: "none", zIndex: "2147483644",
      display: "none",
    });
    document.body.appendChild(regionBox);
  }

  async function sendPendingCapture() {
    if (!pendingCapture) return;
    const result = await sendCapture(pendingCapture, pendingCaptureTarget);
    if (result) {
      // Success — sendCapture put the button into "✓" state. Hold that
      // confirmation for SUCCESS_FLASH_MS before tearing down the
      // subpanel so the user has a clear in-focus signal that the
      // capture went through.
      pendingCapture = null;
      pendingCaptureTarget = null;
      await new Promise(r => setTimeout(r, SUCCESS_FLASH_MS));
      if (regionBox) { regionBox.style.display = "none"; regionBox.style.borderColor = "#3b82f6"; }
      if (highlightBox) { highlightBox.style.borderColor = "#3b82f6"; }
      hideSubpanel();
    } else {
      // Failure — leave the staged capture + subpanel so the user can retry
      // without re-selecting. sendCapture already reset button to "idle"
      // and showed an error toast.
      updateSubpanelHint("Send failed — try again, or Esc to cancel");
    }
  }

  // ─── Annotation canvas ───
  function createCanvas() {
    const dpr = window.devicePixelRatio || 1;
    const w = window.innerWidth;
    const h = window.innerHeight;

    // Save scroll position and prevent scrolling without layout shift
    savedScroll = { x: window.scrollX, y: window.scrollY };
    window.__peekPreventScroll = (e) => {
      e.preventDefault();
    };
    window.addEventListener("wheel", window.__peekPreventScroll, { passive: false });
    window.addEventListener("touchmove", window.__peekPreventScroll, { passive: false });

    // Transparent canvas overlay — user draws on top of the live page
    canvas = document.createElement("canvas");
    canvas.id = NS + "canvas";
    canvas.width = w * dpr;
    canvas.height = h * dpr;
    Object.assign(canvas.style, {
      position: "fixed", top: "0", left: "0",
      width: w + "px", height: h + "px",
      zIndex: "2147483645", cursor: "crosshair",
      background: "transparent",
    });
    canvasCtx = canvas.getContext("2d");
    canvasCtx.scale(dpr, dpr);
    isolateEvents(canvas);
    document.body.appendChild(canvas);


    // Canvas events
    canvas.addEventListener("mousedown", annotateMouseDown);
    canvas.addEventListener("mousemove", annotateMouseMove);
    canvas.addEventListener("mouseup", annotateMouseUp);
  }

  // ─── Annotation drawing (freehand only) ───
  function annotateMouseDown(e) {
    drawing = true;
    const x = e.clientX, y = e.clientY;
    annotateLastPos = { x, y };
    canvasCtx.beginPath();
    canvasCtx.moveTo(x, y);
    canvasCtx.strokeStyle = "#ef4444";
    canvasCtx.lineWidth = 3;
    canvasCtx.lineCap = "round";
  }

  function annotateMouseMove(e) {
    if (!drawing) return;
    const x = e.clientX, y = e.clientY;
    canvasCtx.lineTo(x, y);
    canvasCtx.stroke();
    annotateLastPos = { x, y };
  }

  function annotateMouseUp(e) {
    drawing = false;
  }

  // ─── Calculate bounding box of drawn annotation strokes ───
  function getAnnotationBounds() {
    const dpr = window.devicePixelRatio || 1;
    const imageData = canvasCtx.getImageData(0, 0, canvas.width, canvas.height);
    const data = imageData.data;
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    let hasPixels = false;

    // Scan every pixel to find drawn content (non-transparent pixels)
    for (let py = 0; py < canvas.height; py++) {
      for (let px = 0; px < canvas.width; px++) {
        const alpha = data[(py * canvas.width + px) * 4 + 3];
        if (alpha > 10) { // non-transparent
          // Convert physical pixel back to CSS coordinates
          const cssX = px / dpr;
          const cssY = py / dpr;
          if (cssX < minX) minX = cssX;
          if (cssY < minY) minY = cssY;
          if (cssX > maxX) maxX = cssX;
          if (cssY > maxY) maxY = cssY;
          hasPixels = true;
        }
      }
    }

    if (!hasPixels) return null;

    // Add small padding around the annotation bounds
    const pad = 10;
    return {
      x: Math.max(0, minX - pad),
      y: Math.max(0, minY - pad),
      width: (maxX - minX) + pad * 2,
      height: (maxY - minY) + pad * 2,
    };
  }

  async function sendAnnotation() {
    const w = window.innerWidth;

    // Calculate the exact bounding box of drawn annotation strokes
    const annotBounds = getAnnotationBounds();
    if (!annotBounds) {
      showToast("No annotation drawn", true);
      return;
    }

    // Canvas is position:fixed top:0 left:0 (since v0.5.1 pill toolbar).
    // Its coordinates already match viewport coordinates 1:1.
    const viewportRect = {
      x: annotBounds.x,
      y: annotBounds.y,
      width: annotBounds.width,
      height: annotBounds.height,
    };

    // Only get elements that intersect with the annotation area
    const elements = getElementsInRect(viewportRect);

    // Annotation canvas (transparent bg with red drawings)
    const annotationBase64 = canvas.toDataURL("image/png").split(",")[1];

    // Annotate draws over the whole page, so we need full-viewport context
    // as the backdrop — no smarter target available. This is the one mode
    // that may take >300ms; the delayed loading indicator covers it.
    const result = await sendCapture({
      mode: "annotate",
      url: safeUrl(),
      viewport: { width: w, height: window.innerHeight },
      scroll: { x: savedScroll.x, y: savedScroll.y },
      annotationBounds: {
        x: Math.round(viewportRect.x),
        y: Math.round(viewportRect.y),
        width: Math.round(viewportRect.width),
        height: Math.round(viewportRect.height),
      },
      elements,
      screenshotBase64: annotationBase64,
    }, document.documentElement);
    if (result) {
      // Hold ✓ briefly for confirmation, then reset to idle. Unlike
      // Element/Region we don't hide the subpanel — the user may want
      // to keep drawing and sending more annotations on the same page.
      await new Promise(r => setTimeout(r, SUCCESS_FLASH_MS));
      setSendBtnState("idle");
    }
  }

  // ─── Mode management ───
  function setMode(newMode) {
    cleanupMode();
    mode = mode === newMode ? null : newMode;

    // Update toolbar button styles
    toolbar.querySelectorAll("button[data-mode]").forEach(btn => {
      btn.style.background = btn.dataset.mode === mode ? "#3b82f6" : "rgba(255,255,255,0.1)";
    });

    if (!mode) return;

    if (mode === "region") {
      createOverlay();
      createRegionBox();
      overlay.style.cursor = "crosshair";
      overlay.addEventListener("mousedown", regionMouseDown);
      overlay.addEventListener("mousemove", regionMouseMove);
      overlay.addEventListener("mouseup", regionMouseUp);
      // Subpanel reveals itself after the first drag completes.
    } else if (mode === "select") {
      createOverlay();
      createHighlightBox();
      overlay.style.cursor = "default";
      overlay.addEventListener("mousemove", selectMouseMove);
      overlay.addEventListener("click", selectClick);
      // Subpanel reveals itself after an element is clicked.
    } else if (mode === "annotate") {
      createCanvas();
      showSubpanel({ onSend: sendAnnotation });
    }
    updateModeTip();
  }

  function cleanupMode() {
    overlay?.remove(); overlay = null;
    highlightBox?.remove(); highlightBox = null;
    regionBox?.remove(); regionBox = null;
    canvas?.remove(); canvas = null;
    hideSubpanel();
    if (modeTip) modeTip.style.display = "none";
    regionStart = null;
    drawing = false;
    pendingCapture = null;
    pendingCaptureTarget = null;
    // Restore scrolling when leaving annotate mode
    if (window.__peekPreventScroll) {
      window.removeEventListener("wheel", window.__peekPreventScroll);
      window.removeEventListener("touchmove", window.__peekPreventScroll);
      delete window.__peekPreventScroll;
    }
  }

  // ─── Region select handlers ───
  function regionMouseDown(e) {
    regionStart = { x: e.clientX, y: e.clientY };
    regionBox.style.display = "block";
    regionBox.style.left = e.clientX + "px";
    regionBox.style.top = e.clientY + "px";
    regionBox.style.width = "0";
    regionBox.style.height = "0";
  }

  function regionMouseMove(e) {
    if (!regionStart) return;
    const x = Math.min(regionStart.x, e.clientX);
    const y = Math.min(regionStart.y, e.clientY);
    const w = Math.abs(e.clientX - regionStart.x);
    const h = Math.abs(e.clientY - regionStart.y);
    regionBox.style.left = x + "px";
    regionBox.style.top = y + "px";
    regionBox.style.width = w + "px";
    regionBox.style.height = h + "px";
  }

  function regionMouseUp(e) {
    if (!regionStart) return;
    const rect = {
      x: Math.min(regionStart.x, e.clientX),
      y: Math.min(regionStart.y, e.clientY),
      width: Math.abs(e.clientX - regionStart.x),
      height: Math.abs(e.clientY - regionStart.y),
    };
    regionStart = null;

    if (rect.width < 5 || rect.height < 5) {
      regionBox.style.display = "none";
      return;
    }

    // Visual feedback — keep box visible
    regionBox.style.borderColor = "#22c55e";

    const elements = getElementsInRect(rect);

    // Stage capture data, don't send yet
    pendingCapture = {
      mode: "region",
      url: safeUrl(),
      viewport: { width: window.innerWidth, height: window.innerHeight },
      scroll: { x: window.scrollX, y: window.scrollY },
      region: { x: Math.round(rect.x), y: Math.round(rect.y), width: Math.round(rect.width), height: Math.round(rect.height) },
      elements,
    };
    // Pre-compute the tightest DOM subtree to rasterize when Send is hit.
    // Doing it here (cheap; just a parent-walk) means click→Send latency
    // stays small even on huge pages.
    pendingCaptureTarget = smallestContainerOfRect(rect);
    showSubpanel({
      hintText: `Region: ${elements.length} element${elements.length !== 1 ? "s" : ""} — re-drag to adjust`,
      onSend: sendPendingCapture,
    });
  }

  // ─── Element select handlers ───
  let lastHoveredEl = null;

  function selectMouseMove(e) {
    // Find element under overlay
    overlay.style.pointerEvents = "none";
    const el = document.elementFromPoint(e.clientX, e.clientY);
    overlay.style.pointerEvents = "";

    if (!el || el.id?.startsWith(NS) || el.closest(`[id^="${NS}"]`)) {
      lastHoveredEl = null;
      if (!pendingCapture) highlightBox.style.display = "none";
      return;
    }

    // Skip body/html — selecting the whole page is never useful
    const tag = el.tagName.toLowerCase();
    if (tag === "body" || tag === "html") {
      lastHoveredEl = null;
      if (!pendingCapture) highlightBox.style.display = "none";
      return;
    }

    lastHoveredEl = el;
    // Once a selection is committed (user clicked), stop following the mouse.
    // The highlight stays locked on the chosen element until the user sends
    // or picks a different element by clicking again.
    if (pendingCapture) return;

    const r = el.getBoundingClientRect();
    highlightBox.style.display = "block";
    highlightBox.style.left = r.left + "px";
    highlightBox.style.top = r.top + "px";
    highlightBox.style.width = r.width + "px";
    highlightBox.style.height = r.height + "px";
  }

  function selectClick(e) {
    if (!lastHoveredEl) return;
    const el = lastHoveredEl;
    const r = el.getBoundingClientRect();

    // Lock the highlight box to this element (don't wait for a hover event —
    // the user may not move the mouse again before hitting Send).
    highlightBox.style.display = "block";
    highlightBox.style.left = r.left + "px";
    highlightBox.style.top = r.top + "px";
    highlightBox.style.width = r.width + "px";
    highlightBox.style.height = r.height + "px";
    highlightBox.style.borderColor = "#22c55e";

    // Stage capture data, don't send yet
    pendingCapture = {
      mode: "element",
      url: safeUrl(),
      viewport: { width: window.innerWidth, height: window.innerHeight },
      scroll: { x: window.scrollX, y: window.scrollY },
      region: { x: Math.round(r.x), y: Math.round(r.y), width: Math.round(r.width), height: Math.round(r.height) },
      elements: [{
        selector: getSelector(el),
        tagName: el.tagName.toLowerCase(),
        classes: Array.from(el.classList).filter(c => !c.startsWith(NS)),
        id: el.id || "",
        text: (el.textContent || "").trim().slice(0, 500),
        outerHTML: sanitizeOuterHTML(el),
        boundingBox: { x: Math.round(r.x), y: Math.round(r.y), width: Math.round(r.width), height: Math.round(r.height) },
        styles: getKeyStyles(el),
        domContext: getDOMContext(el),
      }],
    };
    // Render only the picked element's subtree on Send — the dramatic
    // speed win over rasterizing documentElement.
    pendingCaptureTarget = el;
    const tag = el.tagName.toLowerCase();
    const id = el.id ? `#${el.id}` : "";
    showSubpanel({
      hintText: `Element: <${tag}${id}> — click another to change`,
      onSend: sendPendingCapture,
    });
  }

  // ─── Keyboard shortcuts ───
  function handleKeydown(e) {
    if (e.altKey && e.key === "r") { e.preventDefault(); setMode("region"); }
    if (e.altKey && e.key === "s") { e.preventDefault(); setMode("select"); }
    if (e.altKey && e.key === "a") { e.preventDefault(); setMode("annotate"); }
    if (e.key === "Escape") { if (mode) { setMode(null); } else { destroy(); } }
  }

  document.addEventListener("keydown", handleKeydown, true);

  // ─── Cleanup ───
  function destroy() {
    cleanupMode();
    toolbar?.__dragTeardown?.();
    toolbar?.__captureBlocker?.();
    toolbar?.remove();
    document.removeEventListener("keydown", handleKeydown, true);
    window.__inspectorActive = false;
    window.__inspectorLoaded = false;
    delete window.__inspectorVersion;
    delete window.__peekTeardown;
  }

  // Expose the teardown globally so the next-loaded inspector.js version
  // can cleanly take over without the user having to reload the page.
  // See the version-mismatch branch at the top of this IIFE.
  window.__peekTeardown = destroy;

  // ─── Init ───
  createToolbar();
  showToast("Peek ready — choose a mode");
})();
