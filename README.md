# Peek

Point at your UI. Your AI agent sees it.

## Why

AI coding agents can edit code, but they can't see your page. You end up describing layouts in words, copy-pasting HTML, or dragging screenshots into chat. It works, but it's tedious.

Peek fixes this. Click a bookmarklet, point at something, and your AI agent instantly gets a screenshot plus the element data (selectors, styles, bounding boxes). You point, it sees.

## Quick Start

```bash
pip install peek-mcp
playwright install chromium   # headless browser for screenshots (~150MB, one-time)
```

Add Peek to your MCP client (one-time):

<details>
<summary><b>Claude Code</b></summary>

```bash
# Current project only
claude mcp add peek -- $(which peek) mcp

# Or, all projects (global)
claude mcp add -s user peek -- $(which peek) mcp
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

Then start Peek and grab the bookmarklet:

```bash
peek mcp
```

Open http://localhost:8899, drag the blue button to your bookmark bar. That's it.

## Usage

Open any localhost page. Click the bookmarklet. Pick a mode:

| Mode | Shortcut | You do | Agent gets |
|------|----------|--------|------------|
| **Region** | `Alt+R` | Drag a rectangle | Screenshot + elements in that area |
| **Element** | `Alt+S` | Click an element | Screenshot + selector, styles, HTML |
| **Annotate** | `Alt+A` | Draw (pen, box, arrow) | Screenshot + your drawings + elements |

After selecting, tell your agent to look — something like "I captured the button, take a look" or "check what I just selected". The agent will call `get_latest_capture()` and see your screenshot + element data.

Your agent can also take screenshots on its own — just ask "screenshot localhost:3000" or "take a look at the page". No bookmarklet needed for this; the agent calls `screenshot(url)` directly.

## How It Works

```
You select something with the bookmarklet
    → Peek grabs the element data, sends it to the local bridge server
    → Bridge server takes a Playwright screenshot of the page
    → Your AI agent calls get_latest_capture() and sees everything
    → "The chart legend overlaps the bars. Fixing the CSS..."
```

One process, two jobs: MCP server talks to your AI agent over stdio, bridge server receives bookmarklet data on port 8899. `peek mcp` runs both.

## MCP Tools

| Tool | What it does |
|------|-------------|
| `get_latest_capture()` | Returns your latest selection — screenshot + element data |
| `screenshot(url)` | Takes a fresh screenshot (useful after code changes) |

## CLI

```bash
peek mcp                  # start everything (recommended)
peek mcp --port 9000      # different bridge port
```

## Tips

**Help your agent find your dev server.** The `screenshot(url)` tool needs to know where your app is running. Add this to your project instructions (`CLAUDE.md`, `.cursorrules`, etc.):

```
Dev server runs on http://localhost:3000
```

Or just tell the agent the port in conversation. To make it always ask when it doesn't know:

```
When using Peek's screenshot tool and you don't know the dev server URL, ask me which port the app is running on before taking a screenshot.
```

**Multiple localhost servers?** If you have several apps running, the agent may screenshot the wrong one. Adding the port to your project instructions (see above) prevents this.

**Bookmarklet not working?** Delete it from your bookmark bar and re-drag from http://localhost:8899.

## Limitations

- **Localhost only.** Bookmarklet and screenshots work with `localhost` and `127.0.0.1`.
- **No auth.** Playwright uses a fresh browser — no cookies, no login state.
- **Captures may contain sensitive data.** Passwords and hidden inputs are redacted, but visible text and screenshots are saved as-is to `captures/` (gitignored by default).

## Requirements

- Python 3.10+
- Playwright Chromium (`playwright install chromium`)
