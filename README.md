# UI Inspector

Let AI agents see your UI — point at elements, annotate, and get instant visual context for AI-powered code editing.

## Quick Start

### 1. Install

```bash
pip install ui-inspector
playwright install chromium
```

### 2. Configure Claude Code MCP

```bash
claude mcp add ui-inspector -- ui-inspector mcp
```

This registers UI Inspector as a tool that Claude Code can call directly.

### 3. Install the Bookmarklet

```bash
ui-inspector serve
```

Open http://localhost:8899 and drag the blue "UI Inspector" button to your bookmark bar. This is a one-time setup.

## Usage

Open any localhost page and click the bookmarklet. Three modes are available:

| Mode | Shortcut | What it does |
|------|----------|-------------|
| Region Select | `Alt+R` | Drag a rectangle to select an area |
| Element Select | `Alt+S` | Hover to highlight, click to select |
| Annotate | `Alt+A` | Draw on the page (pen, rectangle, arrow) |

After selecting or annotating, Claude Code automatically receives the screenshot and element data via MCP.

## CLI Commands

### `ui-inspector mcp` (recommended)

Starts the MCP server (for Claude Code) with the bridge server embedded. This is what `claude mcp add` points to.

```bash
ui-inspector mcp [--port 8899] [--host 0.0.0.0]
```

### `ui-inspector serve`

Starts only the bridge server. Use this if you don't need MCP integration.

```bash
ui-inspector serve [--port 8899] [--host 0.0.0.0]
```

## How It Works

```
You (browser + bookmarklet)
    │  select region / element / annotate
    │  POST to bridge server
    ▼
Bridge Server (FastAPI, port 8899)
    │  Playwright screenshot + save metadata
    ▼
captures/ directory
    │  JSON + PNG files
    ▼
MCP Server (stdio)
    │  Claude Code calls get_latest_capture()
    │  or screenshot(url) to see any page
    ▼
Claude Code
    understands your UI, edits code accordingly
```

## MCP Tools

| Tool | Description |
|------|-------------|
| `screenshot(url, scroll_y, width, height)` | Take a screenshot of any URL |
| `get_latest_capture()` | Get the latest bookmarklet capture (screenshot + element data) |

## Requirements

- Python 3.10+
- Playwright Chromium (`playwright install chromium`)
