# Peek

Give your AI coding agent eyes. Point at your UI, and it sees exactly what you see.

## The Problem

You're using Claude Code to edit your frontend. You say "move that button to the right." Claude asks: *which button? where is it? what does the page look like?*

You end up copy-pasting HTML, describing layouts in words, taking screenshots and dragging them into chat. It works, but it's slow and lossy.

## How Peek Solves It

Peek is a bookmarklet. You click it on any localhost page, point at what you want to change — a region, an element, or draw on the page — and Claude Code instantly sees:

- A pixel-perfect screenshot of what you're looking at
- The exact CSS selectors, styles, and bounding boxes of the elements you pointed at
- Your annotations (circles, arrows, highlights) overlaid on the screenshot

No copy-pasting. No describing. You point, AI sees.

## Quick Start

### 1. Install

```bash
pip install peek
playwright install chromium   # downloads a headless browser for screenshots (~150MB, one-time)
```

### 2. Set up Claude Code

```bash
claude mcp add peek -- peek mcp
```

This tells Claude Code that Peek exists. From now on, Claude can call `screenshot()` and `get_latest_capture()` as tools — you never need to run this command again.

### 3. Install the bookmarklet (one-time)

Start Peek, then open http://localhost:8899 in your browser:

```bash
peek mcp
```

Drag the blue "Peek" button to your bookmark bar. Done — you won't need to do this again.

### 4. Use it

1. Open your localhost dev page
2. Click "Peek" in your bookmark bar
3. Choose a mode and select what you want Claude to see
4. Tell Claude what to change — it already has the visual context

## Three Modes

| Mode | Shortcut | What you do | What Claude gets |
|------|----------|------------|-----------------|
| **Region Select** | `Alt+R` | Drag a rectangle over an area | Screenshot of that area + all elements inside it |
| **Element Select** | `Alt+S` | Hover and click one element | Screenshot + that element's selector, styles, HTML |
| **Annotate** | `Alt+A` | Draw on the page (pen, rectangle, arrow) | Screenshot + your drawings overlaid + elements in the drawn area |

## How It Works

```
You: click bookmarklet, select a region
         │
         ▼
    Peek captures element data
    and sends it to the bridge server
         │
         ▼
    Bridge server takes a Playwright
    screenshot of the same page area
         │
         ▼
    Claude Code calls get_latest_capture()
    → receives screenshot + element metadata
         │
         ▼
    Claude: "I can see the chart legend is overlapping
    the bars. Let me fix the CSS..."
```

Peek runs as a single process: the MCP server (talking to Claude Code via stdio) and the bridge server (receiving bookmarklet data on port 8899) run together. You only need `peek mcp`.

## MCP Tools

Claude Code can call these tools automatically:

| Tool | When Claude uses it |
|------|-------------------|
| `get_latest_capture()` | After you select/annotate something — gets your screenshot + element data |
| `screenshot(url)` | When Claude wants to check a page on its own (e.g., after making a code change) |

## CLI

```bash
peek mcp                  # start everything (recommended)
peek mcp --port 9000      # use a different port for the bridge server
peek serve                # start only the bridge server (no MCP, for manual use)
```

## Limitations

- **Localhost only** — Peek is designed for local development. The bookmarklet and screenshot engine only work with `localhost` / `127.0.0.1` URLs.
- **No login state** — Playwright opens a fresh browser for screenshots. If your page requires authentication, the screenshot won't show the logged-in state.
- **Sensitive data** — Screenshots and element data (HTML, text content) are saved to a local `captures/` directory. Password fields and hidden inputs are automatically redacted, but visible page content is captured as-is. The `captures/` directory is gitignored by default.

## Requirements

- Python 3.10+
- Playwright Chromium — installed automatically via `playwright install chromium`
