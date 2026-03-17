# Peek

Point at your UI. Your AI agent sees it.

## Why

AI coding agents can edit code, but they can't see your page. You end up describing layouts in words, copy-pasting HTML, or dragging screenshots into chat. It works, but it's tedious.

Peek fixes this. Click a bookmarklet, point at something, and Claude Code instantly gets a screenshot plus the element data (selectors, styles, bounding boxes). You point, it sees.

## Quick Start

```bash
pip install peek
playwright install chromium   # headless browser for screenshots (~150MB, one-time)
```

Tell Claude Code about Peek (one-time):

```bash
claude mcp add peek -- peek mcp
```

Start Peek and grab the bookmarklet:

```bash
peek mcp
```

Open http://localhost:8899, drag the blue button to your bookmark bar. That's it.

## Usage

Open any localhost page. Click the bookmarklet. Pick a mode:

| Mode | Shortcut | You do | Claude gets |
|------|----------|--------|-------------|
| **Region** | `Alt+R` | Drag a rectangle | Screenshot + elements in that area |
| **Element** | `Alt+S` | Click an element | Screenshot + selector, styles, HTML |
| **Annotate** | `Alt+A` | Draw (pen, box, arrow) | Screenshot + your drawings + elements |

Then just tell Claude what to change. It already has the context.

## How It Works

```
You select something with the bookmarklet
    → Peek grabs the element data, sends it to the local bridge server
    → Bridge server takes a Playwright screenshot of the page
    → Claude Code calls get_latest_capture() and sees everything
    → "The chart legend overlaps the bars. Fixing the CSS..."
```

One process, two jobs: MCP server talks to Claude Code over stdio, bridge server receives bookmarklet data on port 8899. `peek mcp` runs both.

## MCP Tools

| Tool | What it does |
|------|-------------|
| `get_latest_capture()` | Returns your latest selection — screenshot + element data |
| `screenshot(url)` | Takes a fresh screenshot (useful after code changes) |

## CLI

```bash
peek mcp                  # start everything (recommended)
peek mcp --port 9000      # different bridge port
peek serve                # bridge server only, no MCP
```

## Limitations

- **Localhost only.** Bookmarklet and screenshots work with `localhost` and `127.0.0.1`.
- **No auth.** Playwright uses a fresh browser — no cookies, no login state.
- **Captures may contain sensitive data.** Passwords and hidden inputs are redacted, but visible text and screenshots are saved as-is to `captures/` (gitignored by default).

## Requirements

- Python 3.10+
- Playwright Chromium (`playwright install chromium`)
