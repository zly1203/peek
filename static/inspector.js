/**
 * Peek — inject into any localhost page via bookmarklet.
 * Provides region select, element select, and annotation modes.
 * Sends captures to bridge server at localhost:8899.
 */
(function () {
  if (window.__inspectorActive) return;
  window.__inspectorActive = true;

  const BRIDGE = window.__PEEK_BRIDGE_URL || "http://localhost:8899";
  const NS = "__uiinsp_"; // namespace prefix for all injected elements

  // ─── State ───
  let mode = null; // 'region' | 'select' | 'annotate' | null
  let overlay, toolbar, highlightBox, regionBox, canvas, canvasCtx;
  let regionStart = null;
  let drawing = false;
  let savedScroll = { x: 0, y: 0 }; // saved scroll position for annotate mode
  let annotateLastPos = null;
  let annotateTool = "freehand"; // 'freehand' | 'rect' | 'arrow'
  let annotateShapes = [];
  let annotateCurrentShape = null;

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

  // ─── Send capture to bridge ───
  async function sendCapture(data) {
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
  function createToolbar() {
    toolbar = document.createElement("div");
    toolbar.id = NS + "toolbar";
    Object.assign(toolbar.style, {
      position: "fixed", top: "0", left: "0", right: "0", height: "40px",
      background: "rgba(15, 23, 42, 0.92)", backdropFilter: "blur(8px)",
      display: "flex", alignItems: "center", justifyContent: "center", gap: "4px",
      zIndex: "2147483646", fontFamily: "-apple-system, system-ui, sans-serif",
      borderBottom: "1px solid rgba(255,255,255,0.1)",
    });

    const btnStyle = {
      padding: "5px 14px", border: "none", borderRadius: "6px",
      color: "white", fontSize: "13px", cursor: "pointer",
      background: "rgba(255,255,255,0.1)", transition: "background 0.15s",
    };

    function makeBtn(label, shortcut, onClick) {
      const btn = document.createElement("button");
      btn.textContent = `${label} (${shortcut})`;
      btn.dataset.mode = label.toLowerCase();
      Object.assign(btn.style, btnStyle);
      btn.addEventListener("click", onClick);
      btn.addEventListener("mouseenter", () => { if (btn.dataset.mode !== mode) btn.style.background = "rgba(255,255,255,0.2)"; });
      btn.addEventListener("mouseleave", () => { if (btn.dataset.mode !== mode) btn.style.background = "rgba(255,255,255,0.1)"; });
      return btn;
    }

    const regionBtn = makeBtn("Region", "Alt+R", () => setMode("region"));
    const selectBtn = makeBtn("Select", "Alt+S", () => setMode("select"));
    const annotateBtn = makeBtn("Annotate", "Alt+A", () => setMode("annotate"));

    const closeBtn = document.createElement("button");
    closeBtn.textContent = "✕";
    Object.assign(closeBtn.style, { ...btnStyle, marginLeft: "12px", color: "#f87171" });
    closeBtn.addEventListener("click", destroy);

    toolbar.append(regionBtn, selectBtn, annotateBtn, closeBtn);
    document.body.appendChild(toolbar);
  }

  // ─── Create overlay (used for region + select modes) ───
  function createOverlay() {
    overlay = document.createElement("div");
    overlay.id = NS + "overlay";
    Object.assign(overlay.style, {
      position: "fixed", top: "40px", left: "0", right: "0", bottom: "0",
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

  // ─── Annotation canvas ───
  function createCanvas() {
    const dpr = window.devicePixelRatio || 1;
    const w = window.innerWidth;
    const h = window.innerHeight - 40;

    // Save scroll position BEFORE freezing
    savedScroll = { x: window.scrollX, y: window.scrollY };
    // Freeze scrolling without jumping
    document.documentElement.style.overflow = "hidden";
    document.body.style.overflow = "hidden";
    window.scrollTo(savedScroll.x, savedScroll.y);

    // Transparent canvas overlay — user draws on top of the live page
    canvas = document.createElement("canvas");
    canvas.id = NS + "canvas";
    canvas.width = w * dpr;
    canvas.height = h * dpr;
    Object.assign(canvas.style, {
      position: "fixed", top: "40px", left: "0",
      width: w + "px", height: h + "px",
      zIndex: "2147483645", cursor: "crosshair",
      background: "transparent",
    });
    canvasCtx = canvas.getContext("2d");
    canvasCtx.scale(dpr, dpr);
    document.body.appendChild(canvas);

    // Annotation sub-toolbar
    const subtoolbar = document.createElement("div");
    subtoolbar.id = NS + "subtoolbar";
    Object.assign(subtoolbar.style, {
      position: "fixed", top: "48px", left: "50%", transform: "translateX(-50%)",
      background: "rgba(15,23,42,0.9)", borderRadius: "8px", padding: "4px 8px",
      display: "flex", gap: "4px", zIndex: "2147483647",
    });

    const tools = [
      { name: "freehand", label: "Pen" },
      { name: "rect", label: "Rect" },
      { name: "arrow", label: "Arrow" },
    ];

    for (const t of tools) {
      const btn = document.createElement("button");
      btn.textContent = t.label;
      btn.dataset.tool = t.name;
      Object.assign(btn.style, {
        padding: "4px 12px", border: "none", borderRadius: "4px",
        color: "white", fontSize: "12px", cursor: "pointer",
        background: t.name === annotateTool ? "#3b82f6" : "rgba(255,255,255,0.1)",
      });
      btn.addEventListener("click", () => {
        annotateTool = t.name;
        subtoolbar.querySelectorAll("button").forEach(b => {
          b.style.background = b.dataset.tool === t.name ? "#3b82f6" : "rgba(255,255,255,0.1)";
        });
      });
      subtoolbar.appendChild(btn);
    }

    // Send button
    const sendBtn = document.createElement("button");
    sendBtn.textContent = "Send";
    Object.assign(sendBtn.style, {
      padding: "4px 16px", border: "none", borderRadius: "4px",
      color: "white", fontSize: "12px", cursor: "pointer",
      background: "#22c55e", marginLeft: "8px",
    });
    sendBtn.addEventListener("click", sendAnnotation);
    subtoolbar.appendChild(sendBtn);

    document.body.appendChild(subtoolbar);

    // Canvas events
    canvas.addEventListener("mousedown", annotateMouseDown);
    canvas.addEventListener("mousemove", annotateMouseMove);
    canvas.addEventListener("mouseup", annotateMouseUp);
  }

  // ─── Annotation drawing ───
  function annotateMouseDown(e) {
    drawing = true;
    const x = e.clientX, y = e.clientY - 40;
    annotateLastPos = { x, y };

    if (annotateTool === "freehand") {
      canvasCtx.beginPath();
      canvasCtx.moveTo(x, y);
      canvasCtx.strokeStyle = "#ef4444";
      canvasCtx.lineWidth = 3;
      canvasCtx.lineCap = "round";
    } else {
      // Save canvas state for rect/arrow preview
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
    const x = e.clientX, y = e.clientY - 40;

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
      } else if (annotateTool === "arrow") {
        drawArrow(canvasCtx, annotateCurrentShape.startX, annotateCurrentShape.startY, x, y);
      }
    }
    annotateLastPos = { x, y };
  }

  function annotateMouseUp(e) {
    drawing = false;
    annotateCurrentShape = null;
  }

  function drawArrow(ctx, fromX, fromY, toX, toY) {
    const headLen = 14;
    const angle = Math.atan2(toY - fromY, toX - fromX);
    ctx.beginPath();
    ctx.moveTo(fromX, fromY);
    ctx.lineTo(toX, toY);
    ctx.lineTo(toX - headLen * Math.cos(angle - Math.PI / 6), toY - headLen * Math.sin(angle - Math.PI / 6));
    ctx.moveTo(toX, toY);
    ctx.lineTo(toX - headLen * Math.cos(angle + Math.PI / 6), toY - headLen * Math.sin(angle + Math.PI / 6));
    ctx.stroke();
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
      overlay.style.cursor = "crosshair";
      overlay.addEventListener("mousedown", regionMouseDown);
      overlay.addEventListener("mousemove", regionMouseMove);
      overlay.addEventListener("mouseup", regionMouseUp);
    } else if (mode === "select") {
      createOverlay();
      createHighlightBox();
      overlay.style.cursor = "default";
      overlay.addEventListener("mousemove", selectMouseMove);
      overlay.addEventListener("click", selectClick);
    } else if (mode === "annotate") {
      createCanvas();
    }
  }

  function cleanupMode() {
    overlay?.remove(); overlay = null;
    highlightBox?.remove(); highlightBox = null;
    regionBox?.remove(); regionBox = null;
    canvas?.remove(); canvas = null;
    document.getElementById(NS + "subtoolbar")?.remove();
    regionStart = null;
    drawing = false;
    // Restore scrolling when leaving annotate mode
    document.documentElement.style.overflow = "";
    document.body.style.overflow = "";
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

  async function regionMouseUp(e) {
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

    // Brief visual feedback
    regionBox.style.borderColor = "#22c55e";

    const elements = getElementsInRect(rect);

    await sendCapture({
      mode: "region",
      url: safeUrl(),
      viewport: { width: window.innerWidth, height: window.innerHeight },
      scroll: { x: window.scrollX, y: window.scrollY },
      region: { x: Math.round(rect.x), y: Math.round(rect.y), width: Math.round(rect.width), height: Math.round(rect.height) },
      elements,
    });

    regionBox.style.display = "none";
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

    lastHoveredEl = el;
    const r = el.getBoundingClientRect();
    highlightBox.style.display = "block";
    highlightBox.style.left = r.left + "px";
    highlightBox.style.top = r.top + "px";
    highlightBox.style.width = r.width + "px";
    highlightBox.style.height = r.height + "px";
  }

  async function selectClick(e) {
    if (!lastHoveredEl) return;
    const el = lastHoveredEl;
    const r = el.getBoundingClientRect();

    highlightBox.style.borderColor = "#22c55e";

    await sendCapture({
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
      }],
    });

    highlightBox.style.borderColor = "#3b82f6";
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
    toolbar?.remove();
    document.removeEventListener("keydown", handleKeydown, true);
    window.__inspectorActive = false;
    window.__inspectorLoaded = false;
  }

  // ─── Init ───
  createToolbar();
  showToast("Peek ready — choose a mode");
})();
