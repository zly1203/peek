/**
 * Peek — inject into any localhost page via bookmarklet.
 * Provides region select, element select, and annotation modes.
 * Sends captures to bridge server at localhost:8899.
 */
const __PEEK_INSPECTOR_VERSION = "0.5.2";

(function () {
  if (window.__inspectorActive) {
    // Same page, already loaded. If version differs, user is on a
    // stale copy after a server upgrade — ask them to reload.
    if (window.__inspectorVersion !== __PEEK_INSPECTOR_VERSION) {
      const prev = window.__inspectorVersion || "pre-0.5";
      console.warn(
        `[Peek] Version mismatch on this page (loaded: ${prev}, latest: ${__PEEK_INSPECTOR_VERSION}). ` +
        `Reload to use the new version.`
      );
      alert(
        `Peek has been upgraded (was ${prev}, now ${__PEEK_INSPECTOR_VERSION}).\n\n` +
        `Please reload this page to use the new version.`
      );
    }
    return;
  }
  window.__inspectorActive = true;
  window.__inspectorVersion = __PEEK_INSPECTOR_VERSION;

  const BRIDGE = window.__PEEK_BRIDGE_URL || "http://localhost:8899";
  const NS = "__uiinsp_"; // namespace prefix for all injected elements

  // ─── State ───
  let mode = null; // 'region' | 'select' | 'annotate' | null
  let overlay, toolbar, subtoolbar, highlightBox, regionBox, canvas, canvasCtx, sendBar;
  let regionStart = null;
  let drawing = false;
  let savedScroll = { x: 0, y: 0 }; // saved scroll position for annotate mode
  let annotateLastPos = null;
  let annotateTool = "freehand"; // 'freehand' | 'rect'
  let annotateShapes = [];
  let annotateCurrentShape = null;
  let pendingCapture = null; // staged capture data waiting for Send

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

  async function captureFullPagePng() {
    // Hide Peek's own UI so it doesn't appear in the capture
    const peekEls = Array.from(document.querySelectorAll(`[id^="${NS}"]`));
    const originalVisibility = peekEls.map(el => ({ el, visibility: el.style.visibility }));
    peekEls.forEach(el => { el.style.visibility = "hidden"; });

    try {
      await ensureModernScreenshotLoaded();
      // Let the visibility change paint before rendering
      await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
      const dataUrl = await window.modernScreenshot.domToPng(document.documentElement, {
        scale: 1,
        width: document.documentElement.scrollWidth,
        height: document.documentElement.scrollHeight,
      });
      // Strip the "data:image/png;base64," prefix
      const comma = dataUrl.indexOf(",");
      return comma >= 0 ? dataUrl.slice(comma + 1) : dataUrl;
    } finally {
      originalVisibility.forEach(({ el, visibility }) => { el.style.visibility = visibility; });
    }
  }

  // ─── Send capture to bridge ───
  async function sendCapture(data) {
    // Attach a client-side PNG when possible so the server can skip the
    // stateless Playwright re-fetch and agents see the user's real state.
    // Silently fall back if modern-screenshot fails — server handles absence.
    try {
      const png = await captureFullPagePng();
      if (png) data.pageScreenshotBase64 = png;
    } catch (e) {
      console.warn("Peek: client-side PNG failed, server will fall back to Playwright", e);
    }

    try {
      const resp = await fetch(`${BRIDGE}/api/capture`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      });
      const result = await resp.json();
      showToast("Captured!");
      return result;
    } catch (e) {
      showToast("Failed — is bridge server running?", true);
      console.error("Peek capture failed:", e);
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

  // ─── Annotate sub-panel: Pen / Rect / Send, attached below the main pill ───
  function createAnnotateSubpanel() {
    subtoolbar = document.createElement("div");
    subtoolbar.id = NS + "subtoolbar";
    Object.assign(subtoolbar.style, {
      position: "absolute",
      left: "0",
      top: "calc(100% + 6px)",
      display: "none",  // revealed by setMode("annotate")
      gap: "4px",
      alignItems: "center",
      background: "rgba(15, 23, 42, 0.85)",
      backdropFilter: "blur(8px)",
      borderRadius: "20px",
      padding: "4px 6px",
      boxShadow: "0 4px 16px rgba(0,0,0,0.25)",
      border: "1px solid rgba(255,255,255,0.1)",
      whiteSpace: "nowrap",
    });

    const toolBtnStyle = {
      padding: "4px 12px", border: "none", borderRadius: "14px",
      color: "white", fontSize: "12px", cursor: "pointer",
      background: "rgba(255,255,255,0.08)", transition: "background 0.15s",
    };

    const tools = [
      { name: "freehand", label: "Pen" },
      { name: "rect", label: "Rect" },
    ];
    for (const t of tools) {
      const btn = document.createElement("button");
      btn.textContent = t.label;
      btn.dataset.tool = t.name;
      Object.assign(btn.style, toolBtnStyle);
      btn.style.background = t.name === annotateTool ? "#3b82f6" : toolBtnStyle.background;
      btn.addEventListener("click", () => {
        annotateTool = t.name;
        subtoolbar.querySelectorAll("button[data-tool]").forEach(b => {
          b.style.background = b.dataset.tool === t.name ? "#3b82f6" : toolBtnStyle.background;
        });
      });
      subtoolbar.appendChild(btn);
    }

    const sendBtn = document.createElement("button");
    sendBtn.textContent = "Send";
    Object.assign(sendBtn.style, {
      ...toolBtnStyle, background: "#22c55e", marginLeft: "4px",
    });
    sendBtn.addEventListener("click", sendAnnotation);
    subtoolbar.appendChild(sendBtn);
  }

  // Flip sub-panel above the pill if there's no room below
  function positionSubpanel() {
    if (!subtoolbar || subtoolbar.style.display === "none") return;
    const pillRect = toolbar.getBoundingClientRect();
    const subH = subtoolbar.offsetHeight || 36;
    const spaceBelow = window.innerHeight - pillRect.bottom;
    if (spaceBelow < subH + 12) {
      subtoolbar.style.top = "auto";
      subtoolbar.style.bottom = "calc(100% + 6px)";
    } else {
      subtoolbar.style.bottom = "auto";
      subtoolbar.style.top = "calc(100% + 6px)";
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

    // Annotate sub-panel — attached to the toolbar so it moves with it.
    // Hidden by default; revealed by setMode("annotate").
    createAnnotateSubpanel();
    toolbar.appendChild(subtoolbar);

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
      // Keep sub-panel on the visible side of the pill while dragging
      positionSubpanel();
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
  function createOverlay() {
    overlay = document.createElement("div");
    overlay.id = NS + "overlay";
    Object.assign(overlay.style, {
      position: "fixed", top: "0", left: "0", right: "0", bottom: "0",
      zIndex: "2147483645", cursor: "default",
    });
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

  // ─── Send bar (shared by region + element modes) ───
  function createSendBar() {
    sendBar = document.createElement("div");
    sendBar.id = NS + "sendbar";
    Object.assign(sendBar.style, {
      position: "fixed", bottom: "24px", left: "50%", transform: "translateX(-50%)",
      background: "rgba(15,23,42,0.9)", borderRadius: "8px", padding: "6px 12px",
      display: "none", gap: "8px", alignItems: "center", zIndex: "2147483647",
      fontFamily: "-apple-system, system-ui, sans-serif",
    });

    const hint = document.createElement("span");
    hint.id = NS + "sendbar_hint";
    Object.assign(hint.style, { color: "rgba(255,255,255,0.6)", fontSize: "12px" });
    hint.textContent = "Select something first";

    const sendBtn = document.createElement("button");
    sendBtn.textContent = "Send";
    sendBtn.id = NS + "sendbar_btn";
    Object.assign(sendBtn.style, {
      padding: "4px 16px", border: "none", borderRadius: "4px",
      color: "white", fontSize: "12px", cursor: "pointer",
      background: "#22c55e", display: "none",
    });
    sendBtn.addEventListener("click", sendPendingCapture);

    sendBar.append(hint, sendBtn);
    document.body.appendChild(sendBar);
  }

  function showSendBar(hintText) {
    if (!sendBar) return;
    const hint = document.getElementById(NS + "sendbar_hint");
    const btn = document.getElementById(NS + "sendbar_btn");
    hint.textContent = hintText;
    btn.style.display = "inline-block";
    sendBar.style.display = "flex";
  }

  async function sendPendingCapture() {
    if (!pendingCapture) return;
    await sendCapture(pendingCapture);
    pendingCapture = null;
    // Hide send button, show hint
    const hint = document.getElementById(NS + "sendbar_hint");
    const btn = document.getElementById(NS + "sendbar_btn");
    if (hint) hint.textContent = "Sent! Select again or press Esc";
    if (btn) btn.style.display = "none";
    // Reset visual state
    if (regionBox) { regionBox.style.display = "none"; regionBox.style.borderColor = "#3b82f6"; }
    if (highlightBox) { highlightBox.style.borderColor = "#3b82f6"; }
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
    document.body.appendChild(canvas);


    // Canvas events
    canvas.addEventListener("mousedown", annotateMouseDown);
    canvas.addEventListener("mousemove", annotateMouseMove);
    canvas.addEventListener("mouseup", annotateMouseUp);
  }

  // ─── Annotation drawing ───
  function annotateMouseDown(e) {
    drawing = true;
    const x = e.clientX, y = e.clientY;
    annotateLastPos = { x, y };

    if (annotateTool === "freehand") {
      canvasCtx.beginPath();
      canvasCtx.moveTo(x, y);
      canvasCtx.strokeStyle = "#ef4444";
      canvasCtx.lineWidth = 3;
      canvasCtx.lineCap = "round";
    } else {
      // Save canvas state for rect preview
      // Must save/restore with scale reset since getImageData uses physical pixels
      const dpr = window.devicePixelRatio || 1;
      canvasCtx.setTransform(1, 0, 0, 1, 0, 0);
      const imageData = canvasCtx.getImageData(0, 0, canvas.width, canvas.height);
      canvasCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
      annotateCurrentShape = {
        tool: annotateTool,
        startX: x, startY: y,
        imageData,
      };
    }
  }

  function annotateMouseMove(e) {
    if (!drawing) return;
    const x = e.clientX, y = e.clientY;

    if (annotateTool === "freehand") {
      canvasCtx.lineTo(x, y);
      canvasCtx.stroke();
    } else if (annotateCurrentShape) {
      // Redraw from saved state and preview shape
      const dpr = window.devicePixelRatio || 1;
      canvasCtx.setTransform(1, 0, 0, 1, 0, 0);
      canvasCtx.putImageData(annotateCurrentShape.imageData, 0, 0);
      canvasCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
      canvasCtx.strokeStyle = "#ef4444";
      canvasCtx.lineWidth = 3;

      if (annotateTool === "rect") {
        canvasCtx.strokeRect(
          annotateCurrentShape.startX, annotateCurrentShape.startY,
          x - annotateCurrentShape.startX, y - annotateCurrentShape.startY
        );
      }
    }
    annotateLastPos = { x, y };
  }

  function annotateMouseUp(e) {
    drawing = false;
    annotateCurrentShape = null;
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

    // Convert canvas coordinates (relative to canvas top-left) to viewport coordinates
    // Canvas starts at y=40 (below toolbar), so add 40 to get viewport y
    const viewportRect = {
      x: annotBounds.x,
      y: annotBounds.y + 40,  // canvas y=0 corresponds to viewport y=40
      width: annotBounds.width,
      height: annotBounds.height,
    };

    // Only get elements that intersect with the annotation area
    const elements = getElementsInRect(viewportRect);

    // Annotation canvas (transparent bg with red drawings)
    const annotationBase64 = canvas.toDataURL("image/png").split(",")[1];

    await sendCapture({
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
    });
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
      createSendBar();
      overlay.style.cursor = "crosshair";
      overlay.addEventListener("mousedown", regionMouseDown);
      overlay.addEventListener("mousemove", regionMouseMove);
      overlay.addEventListener("mouseup", regionMouseUp);
    } else if (mode === "select") {
      createOverlay();
      createHighlightBox();
      createSendBar();
      overlay.style.cursor = "default";
      overlay.addEventListener("mousemove", selectMouseMove);
      overlay.addEventListener("click", selectClick);
    } else if (mode === "annotate") {
      createCanvas();
      subtoolbar.style.display = "flex";
      positionSubpanel();
    }
  }

  function cleanupMode() {
    overlay?.remove(); overlay = null;
    highlightBox?.remove(); highlightBox = null;
    regionBox?.remove(); regionBox = null;
    canvas?.remove(); canvas = null;
    sendBar?.remove(); sendBar = null;
    if (subtoolbar) subtoolbar.style.display = "none";
    regionStart = null;
    drawing = false;
    pendingCapture = null;
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
    showSendBar(`Region: ${elements.length} element${elements.length !== 1 ? "s" : ""} — re-drag to adjust`);
  }

  // ─── Element select handlers ───
  let lastHoveredEl = null;

  function selectMouseMove(e) {
    // Find element under overlay
    overlay.style.pointerEvents = "none";
    const el = document.elementFromPoint(e.clientX, e.clientY);
    overlay.style.pointerEvents = "";

    if (!el || el.id?.startsWith(NS) || el.closest(`[id^="${NS}"]`)) {
      highlightBox.style.display = "none";
      lastHoveredEl = null;
      return;
    }

    // Skip body/html — selecting the whole page is never useful
    const tag = el.tagName.toLowerCase();
    if (tag === "body" || tag === "html") {
      highlightBox.style.display = "none";
      lastHoveredEl = null;
      return;
    }

    lastHoveredEl = el;
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
    const tag = el.tagName.toLowerCase();
    const id = el.id ? `#${el.id}` : "";
    showSendBar(`Element: <${tag}${id}> — click another to change`);
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
    toolbar?.remove();
    document.removeEventListener("keydown", handleKeydown, true);
    window.__inspectorActive = false;
    window.__inspectorLoaded = false;
  }

  // ─── Init ───
  createToolbar();
  showToast("Peek ready — choose a mode");
})();
