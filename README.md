# Peek

Point at your UI. Your AI agent sees it.

## Why

AI coding agents can edit code, but they can't see your page. You end up describing layouts in words, copy-pasting HTML, or dragging screenshots into chat.

Peek fixes this. Your AI agent can screenshot any local page on its own. You can also point at specific elements with a bookmarklet, and the agent gets the screenshot plus element data (selectors, styles, bounding boxes).

## Quick Start

### Claude Code (CLI or VS Code) — recommended

```bash
# 1. Install uv (one-time, manages Python for you)
brew install uv
# or: curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. Install peek (uv auto-downloads a compatible Python)
uv tool install peek-mcp

# 3. One-shot setup
peek setup
```

`peek setup` is one-shot: installs Playwright Chromium, registers Peek as an MCP server in Claude Code (user scope, all projects), drops the bookmarklet page at `~/.peek/bookmarklet.html` and opens it in your browser. Drag the blue button to your bookmark bar and you're done — the command exits on its own. Nothing to keep running.

From then on: **open Claude Code and use it normally.** It auto-launches Peek in the background whenever the agent uses a Peek tool.

> Using pip directly? `pip install peek-mcp` works too, but requires Python 3.10+ already installed. `uv tool install` avoids the version-mismatch headache.

### Upgrading

```bash
uv tool upgrade peek-mcp
```

That's it. The next time Claude Code launches `peek mcp` it'll pick up the new version. Open browser tabs with an old `inspector.js` auto-take-over on the next bookmarklet click.

### Other AI tools (Cursor / Windsurf / Claude Desktop)

```bash
uv tool install peek-mcp
playwright install chromium   # ~150 MB, one-time
```

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

Run `which peek` in your terminal to get the absolute path. Drag the bookmarklet from `~/.peek/bookmarklet.html` (`peek setup` creates it) — no server needed.

### Recommended: tell your agent your dev port

Add this to your project's `CLAUDE.md` (or `.cursorrules`, etc.):

```
Dev server runs on http://localhost:3000

When using Peek's screenshot tool and you don't know the dev server URL, ask me which port the app is running on before taking a screenshot.
```

Replace `3000` with your actual port. **This prevents your agent from guessing the wrong port.**

### Use it

**Agent-driven screenshots (no bookmarklet needed):**

Just ask your agent — "screenshot the page", "take a look at localhost:3000", "check if the button looks right". The agent calls `screenshot(url)` directly.

**User-pointed captures (bookmarklet):**

1. One-time: drag the blue button from `~/.peek/bookmarklet.html` (or any other browser's copy of it) to your bookmark bar
2. Start your AI tool (Claude Code / Cursor / etc.) — it launches peek in the background
3. Open your app, click the bookmarklet, pick a mode:

| Mode | Shortcut | You do | Agent gets |
|------|----------|--------|------------|
| **Region** | `Alt+R` | Drag a rectangle | Screenshot + elements in that area |
| **Element** | `Alt+S` | Click an element | Screenshot + selector, styles, HTML |
| **Annotate** | `Alt+A` | Draw (pen, rect) | Screenshot + your drawings + elements |

4. Tell your agent: "check what I just selected" — it calls `get_user_selection()`

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

| Tool | When to use |
|------|-------------|
| `screenshot(url)` | **Default** — agent fetches any local/LAN URL in a fresh headless browser. Use for general "look at the page" requests, verifying code changes, etc. |
| `get_user_selection()` | Reads what *you* captured with the bookmarklet — a region, element, or annotation. Use when you want the agent to see exactly what you pointed at, including any state that requires your interaction (login, uploaded data, clicked buttons). |

For `Element` mode captures, the agent gets structural context to find the right code:

- **ancestor chain** (`body > main > section.settings > div.flex`)
- **sibling position** (`2 of 3 <button> siblings`)
- **nearest heading** (`h2: Settings`)
- **parent layout** (`flex, row`)

This means when you point at a button, the agent knows *which* button on which section — no guessing.

## How It Works

```
Your AI agent calls screenshot(url)
    -> Playwright takes a fresh headless screenshot (stateless view)
    -> Agent sees the default render of the page

You point at something with the bookmarklet
    -> Bookmarklet renders your CURRENT browser view to PNG client-side
       (so login, uploaded data, clicked buttons are all preserved)
    -> Peek also grabs element metadata (selector, styles, DOM context)
    -> Agent calls get_user_selection() and sees what you see
    -> "The chart legend overlaps the bars. Fixing the CSS..."
```

Client-side rendering uses [modern-screenshot](https://github.com/qq15725/modern-screenshot) (MIT, vendored). If it fails on an exotic page, the bridge falls back to Playwright automatically — or set `PEEK_DOM_SNAPSHOT=0` to force it globally.

## Troubleshooting

**`Playwright Chromium is not installed`**

Run `playwright install chromium`. This downloads the headless browser engine (~150 MB). Only needed once.

**`ERR_CONNECTION_REFUSED` or agent uses the wrong port**

Either your dev server isn't running, or the agent guessed the wrong port. Add the `CLAUDE.md` snippet above so the agent knows your real port; start your dev server before asking for a screenshot.

**Bookmarklet click does nothing**

The bridge server isn't running. Open Claude Code (it auto-launches peek) or run `peek mcp` in a terminal. Run `peek` with no arguments to see install status.

**Need the bookmarklet page again**

Open `~/.peek/bookmarklet.html` in any browser and drag the blue button. No server needed.

**`peek: command not found` after install**

Your scripts directory isn't in PATH. For uv: run `uv tool update-shell` and open a new terminal. For pip: check the install location with `pip show peek-mcp`.

**`No matching distribution found for peek-mcp`**

Your Python is older than 3.10 (common on macOS system Python). Switch to `uv tool install peek-mcp` — uv downloads a compatible Python for you.

**Using Peek from Safari, Firefox, or a different Chrome profile**

Open `~/.peek/bookmarklet.html` in that browser and drag the blue button to its bookmark bar — one-time setup per browser. The `screenshot` tool itself is browser-agnostic (headless Chromium), so it works regardless of your dev browser.

**Screenshot shows a blank or default page instead of what I see**

`screenshot(url)` runs a fresh headless browser — no cookies, no login, no interaction state. For pages behind login / upload / button clicks, use the bookmarklet → `get_user_selection()` instead; it captures your real browser view. If that too looks wrong on an unusual page, try `PEEK_DOM_SNAPSHOT=0` to fall back to Playwright.

**Agent returns a stale screenshot**

`get_user_selection` returns the last bookmarklet capture. Click the bookmarklet again on your current page to refresh it.

## Limitations

- **Local/LAN only.** Public URLs are blocked (SSRF prevention).
- **Bookmarklet render quality varies.** WebGL, cross-origin iframes, and playing videos may not capture faithfully; set `PEEK_DOM_SNAPSHOT=0` to fall back to Playwright.
- **Peek doesn't survive full-page navigation.** Click a link to a new URL and the bookmarklet script is gone — click the bookmarklet again on the new page. Bookmarklet architecture constraint.
- **Captures may contain sensitive data.** Passwords and hidden inputs are redacted, but visible text + screenshots live at `~/.peek/captures/` (last 50 kept, older pruned).

## CLI

```bash
peek                      # status + next step (most users just need this)
peek setup                # one-shot: install, register MCP, drop bookmarklet page
peek mcp                  # advanced — your MCP client auto-launches this
peek mcp --port 9000      # advanced — different bridge port
```

### When do I need to run `peek mcp` manually?

Almost never. Your MCP client launches it for you:

- **Claude Code** — auto-launches `peek mcp` when an agent uses a Peek tool (registered by `peek setup`).
- **Cursor / Windsurf / Claude Desktop** — launch it via their MCP config (point `command` at the `peek` binary with `["mcp"]` args; see each client's MCP docs).

The one case you'd run `peek mcp` by hand: **testing the bookmarklet without any MCP client** — e.g. drawing on a page just to see what data Peek sends, with no agent in the loop. Keep the terminal open while you test; Ctrl+C to stop.

