# Peek

Point at your UI. Your AI agent sees it.

## Why

AI coding agents can edit code, but they can't see your page. You end up describing layouts in words, copy-pasting HTML, or dragging screenshots into chat.

Peek fixes this. Your AI agent can screenshot any local page on its own. You can also point at specific elements with a bookmarklet, and the agent gets the screenshot plus element data (selectors, styles, bounding boxes).

## Quick Start

### 1. Install

```bash
pip install peek-mcp
playwright install chromium   # required: headless browser for screenshots (~150 MB, one-time)
```

Verify it works:

```bash
peek mcp
# You should see: "Bridge server running on http://localhost:8899"
# Press Ctrl+C to stop
```

### 2. Connect to your AI tool

<details>
<summary><b>Claude Code (CLI or VS Code)</b></summary>

```bash
# All projects (recommended)
claude mcp add -s user peek -- $(which peek) mcp

# Or current project only
claude mcp add peek -- $(which peek) mcp
```

> `$(which peek)` resolves to an absolute path, so the MCP server starts correctly even when a project uses a different Python environment.

</details>

<details>
<summary><b>Cursor / Windsurf / Claude Desktop</b></summary>

Add to your MCP config file (e.g. `.cursor/mcp.json`, `~/.codeium/windsurf/mcp_config.json`, or `claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "peek": {
      "command": "/absolute/path/to/peek",
      "args": ["mcp"]
    }
  }
}
```

Run `which peek` in your terminal to get the absolute path.

</details>

### 3. Tell your agent where your dev server runs

Add this to your project's `CLAUDE.md` (or `.cursorrules`, etc.):

```
Dev server runs on http://localhost:3000

When using Peek's screenshot tool and you don't know the dev server URL, ask me which port the app is running on before taking a screenshot.
```

Replace `3000` with your actual port. **This step prevents your agent from guessing the wrong port.**

### 4. Use it

**Agent-driven screenshots (no bookmarklet needed):**

Just ask your agent — "screenshot the page", "take a look at localhost:3000", "check if the button looks right". The agent calls `screenshot(url)` directly.

**User-pointed captures (bookmarklet):**

1. Run `peek mcp` (or let your AI tool start it via MCP)
2. Open http://localhost:8899, drag the blue button to your bookmark bar
3. Open your app, click the bookmarklet, pick a mode:

| Mode | Shortcut | You do | Agent gets |
|------|----------|--------|------------|
| **Region** | `Alt+R` | Drag a rectangle | Screenshot + elements in that area |
| **Element** | `Alt+S` | Click an element | Screenshot + selector, styles, HTML |
| **Annotate** | `Alt+A` | Draw (pen, box, arrow) | Screenshot + your drawings + elements |

4. Tell your agent: "check what I just selected" — it calls `get_latest_capture()`

## Supported URLs

Peek works with local and LAN addresses:

| URL | Supported |
|-----|-----------|
| `http://localhost:3000` | Yes |
| `http://127.0.0.1:8080` | Yes |
| `http://0.0.0.0:5000` | Yes |
| `http://192.168.1.5:3000` | Yes (LAN) |
| `http://myapp.local:3000` | Yes (.local domain) |
| `http://myapp.test:8080` | Yes (.test domain) |
| `https://google.com` | No (public URLs blocked) |

## MCP Tools

| Tool | What it does |
|------|-------------|
| `screenshot(url)` | Takes a screenshot of a local/LAN URL |
| `get_latest_capture()` | Returns your latest bookmarklet selection — screenshot + element data |

## How It Works

```
Your AI agent calls screenshot(url)
    -> Playwright takes a headless screenshot
    -> Agent sees the page and can reason about the UI

You point at something with the bookmarklet
    -> Peek grabs element data + takes a Playwright screenshot
    -> Agent calls get_latest_capture() and sees everything
    -> "The chart legend overlaps the bars. Fixing the CSS..."
```

One process, two jobs: MCP server talks to your AI agent over stdio, bridge server receives bookmarklet data on port 8899. `peek mcp` runs both.

## Troubleshooting

**`Playwright Chromium is not installed`**

Run `playwright install chromium`. This downloads the headless browser engine (~150 MB). Only needed once.

**`ERR_CONNECTION_REFUSED` when taking a screenshot**

Your dev server isn't running on that port. Start your dev server first, then ask the agent to screenshot. If you see this repeatedly, make sure the port in your `CLAUDE.md` matches your actual dev server.

**Agent screenshots the wrong port**

Add the `CLAUDE.md` snippet from step 3 above. Without it, the agent will guess.

**Bookmarklet not working**

Delete it from your bookmark bar and re-drag from http://localhost:8899. Make sure `peek mcp` is running.

**`peek: command not found` after pip install**

Your Python scripts directory may not be in your PATH. Try:
```bash
python -m peek mcp
# or find the path:
pip show peek-mcp | grep Location
```

## Limitations

- **Local/LAN only.** Public URLs are blocked for security (SSRF prevention).
- **No auth.** Playwright uses a fresh browser context — no cookies, no login state.
- **Captures may contain sensitive data.** Passwords and hidden inputs are redacted, but visible text and screenshots are saved as-is to `~/.peek/captures/` (outside your project).

## CLI

```bash
peek mcp                  # start everything (recommended)
peek mcp --port 9000      # different bridge port
```

## Requirements

- Python 3.10+
- Playwright Chromium (`playwright install chromium`)
