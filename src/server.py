"""Peek bridge server — receives captures from browser, saves to disk.
Uses Playwright for reliable server-side screenshots."""

import json
import base64
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Request, Query
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from playwright.async_api import async_playwright
import uvicorn

# ─── Playwright browser (module-level, managed by lifespan) ───
pw = None
browser = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global pw, browser
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    print("Playwright Chromium launched")
    yield
    await browser.close()
    await pw.stop()
    print("Playwright closed")


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_methods=["*"],
    allow_headers=["*"],
)

MAX_BODY_SIZE = 50 * 1024 * 1024  # 50MB


@app.middleware("http")
async def limit_body_size(request: Request, call_next):
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > MAX_BODY_SIZE:
        return JSONResponse({"error": "Request too large"}, status_code=413)
    return await call_next(request)


BASE_DIR = Path(__file__).resolve().parent.parent  # project root (peek/)
CAPTURES_DIR = BASE_DIR / "captures"
STATIC_DIR = BASE_DIR / "static"
CAPTURES_DIR.mkdir(exist_ok=True)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.mount("/captures", StaticFiles(directory=str(CAPTURES_DIR)), name="captures")


# ─── Playwright screenshot helper ───

from .screenshot import take_screenshot


async def playwright_screenshot(url, viewport=None, scroll=None, clip=None):
    """Take a screenshot via Playwright headless Chromium."""
    vp_w = viewport.get("width", 1280) if viewport else 1280
    vp_h = viewport.get("height", 800) if viewport else 800
    scroll_x = int(scroll.get("x", 0)) if scroll else 0
    scroll_y = int(scroll.get("y", 0)) if scroll else 0
    return await take_screenshot(
        browser, url,
        scroll_x=scroll_x, scroll_y=scroll_y, width=vp_w, height=vp_h,
        clip=clip,
    )


# ─── Setup page ───

SETUP_HTML = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>Peek Setup</title>
<style>
  body { font-family: -apple-system, system-ui, sans-serif; max-width: 640px; margin: 60px auto; padding: 0 20px; color: #1a1a1a; line-height: 1.6; }
  h1 { font-size: 1.5rem; }
  .bookmarklet { display: inline-block; padding: 12px 24px; background: #2563eb; color: white; border-radius: 8px; text-decoration: none; font-size: 1rem; cursor: grab; }
  .bookmarklet:hover { background: #1d4ed8; }
  .step { margin: 24px 0; padding: 16px; background: #f8fafc; border-radius: 8px; border-left: 3px solid #2563eb; }
  .step b { color: #2563eb; }
  code { background: #f1f5f9; padding: 2px 6px; border-radius: 4px; font-size: 0.9em; }
  .keys { display: inline-block; padding: 2px 8px; background: #e2e8f0; border-radius: 4px; font-family: monospace; font-size: 0.85em; border: 1px solid #cbd5e1; }
</style>
</head>
<body>
<h1>Peek</h1>
<p>把下面的按钮<b>拖到书签栏</b>，然后在任意 localhost 页面点击即可使用。</p>

<p style="text-align:center; margin: 32px 0;">
  <a class="bookmarklet" href="javascript:(function(){if(window.__inspectorLoaded){return}var s=document.createElement('script');s.src='http://localhost:8899/static/inspector.js?t='+Date.now();s.onload=function(){window.__inspectorLoaded=true};document.head.appendChild(s)})()">
    Peek
  </a>
</p>

<div class="step"><b>Step 1</b> — 保持本服务运行: <code>peek serve</code></div>
<div class="step"><b>Step 2</b> — 把上面蓝色按钮拖到浏览器书签栏</div>
<div class="step"><b>Step 3</b> — 打开任意 localhost 页面，点击书签栏的 "Peek"</div>
<div class="step"><b>Step 4</b> — 使用工具栏选择模式:
  <ul style="margin:8px 0">
    <li><span class="keys">Alt+R</span> 区域选择 — 像截图一样拖拽选区</li>
    <li><span class="keys">Alt+S</span> 元素选择 — 悬停高亮，点击选中</li>
    <li><span class="keys">Alt+A</span> 标注模式 — 在页面上画画标记</li>
  </ul>
</div>
<div class="step"><b>Step 5</b> — 选择/标注后自动保存，告诉 Claude Code 查看即可</div>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
async def setup_page():
    return SETUP_HTML


# ─── Capture endpoint (bookmarklet sends data here) ───

@app.post("/api/capture")
async def receive_capture(request: Request):
    data = await request.json()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    # 1. Save client-side annotation PNG (annotate mode only)
    if "screenshotBase64" in data:
        annot_bytes = base64.b64decode(data["screenshotBase64"])
        if data.get("mode") == "annotate":
            (CAPTURES_DIR / "capture_latest_annot.png").write_bytes(annot_bytes)
            (CAPTURES_DIR / f"capture_{ts}_annot.png").write_bytes(annot_bytes)
            data["annotationOverlay"] = "capture_latest_annot.png"
        del data["screenshotBase64"]

    # 2. Playwright screenshot (real page)
    try:
        clip = data.get("region") or data.get("annotationBounds")
        page_png = await playwright_screenshot(
            url=data["url"],
            viewport=data.get("viewport"),
            scroll=data.get("scroll"),
            clip=clip,
        )
        (CAPTURES_DIR / "capture_latest.png").write_bytes(page_png)
        (CAPTURES_DIR / f"capture_{ts}.png").write_bytes(page_png)
        data["screenshot"] = "capture_latest.png"
    except Exception as e:
        print(f"Playwright screenshot failed: {e}")
        data["screenshot"] = None

    # 3. Save JSON metadata
    data["timestamp"] = ts
    (CAPTURES_DIR / "capture_latest.json").write_text(json.dumps(data, indent=2, ensure_ascii=False))
    (CAPTURES_DIR / f"capture_{ts}.json").write_text(json.dumps(data, indent=2, ensure_ascii=False))

    return {"status": "ok", "timestamp": ts}


# ─── Standalone screenshot endpoint (Claude Code calls directly) ───

@app.get("/api/screenshot")
async def screenshot_endpoint(
    url: str,
    scroll_y: int = Query(0),
    width: int = Query(1280),
    height: int = Query(800),
):
    """Take a screenshot of any URL — for Claude Code to 'see' the page."""
    png = await playwright_screenshot(
        url=url,
        viewport={"width": width, "height": height},
        scroll={"x": 0, "y": scroll_y},
    )
    out = CAPTURES_DIR / "screenshot_latest.png"
    out.write_bytes(png)
    return FileResponse(out, media_type="image/png")


@app.get("/api/capture/latest")
async def latest_capture():
    json_path = CAPTURES_DIR / "capture_latest.json"
    if not json_path.exists():
        return JSONResponse({"status": "no captures yet"}, status_code=404)
    return JSONResponse(json.loads(json_path.read_text()))


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8899)
