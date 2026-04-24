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

`peek setup` does everything for you: installs Playwright Chromium, registers Peek as an MCP server in Claude Code (user scope, all projects), opens the bookmarklet page in your browser. Just drag the blue button to your bookmark bar.

> Using pip directly? `pip install peek-mcp` works too, but requires Python 3.10+ already installed. `uv tool install` avoids the version-mismatch headache.

### Upgrading

```bash
uv tool upgrade peek-mcp
pkill -f "peek mcp"            # or: quit + reopen Claude Code
# then: reload any browser tab that had Peek loaded
```

Three steps because three layers hold a copy of the code: disk (fixed by `uv tool upgrade`), the running `peek mcp` process (fixed by the kill/restart), and any browser page that already loaded the old `inspector.js` (fixed by a page reload). From v0.5.0 onward, Peek detects a stale `inspector.js` automatically and alerts you to reload — so if you forget step 3, you'll see a prompt the next time you click the bookmarklet.

> Don't run `peek setup` to upgrade. `peek setup` is for first-time installs. From v0.5.4 it detects an existing install and exits cleanly, but earlier versions would re-walk you through the bookmarklet drag flow unnecessarily.

**Upgrading from v0.4 → v0.5.x**: also re-drag the blue button from `http://localhost:8899` to your bookmark bar once. The v0.4 bookmarklet JS had a caching gate that v0.5 removed. Future upgrades within the v0.5 line do not require re-dragging.

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

Run `which peek` in your terminal to get the absolute path. Then visit http://localhost:8899 to grab the bookmarklet.

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

1. Run `peek mcp` (or let your AI tool start it via MCP)
2. Open http://localhost:8899, drag the blue button to your bookmark bar
3. Open your app, click the bookmarklet, pick a mode:

| Mode | Shortcut | You do | Agent gets |
|------|----------|--------|------------|
| **Region** | `Alt+R` | Drag a rectangle | Screenshot + elements in that area |
| **Element** | `Alt+S` | Click an element | Screenshot + selector, styles, HTML |
| **Annotate** | `Alt+A` | Draw (pen, box, arrow) | Screenshot + your drawings + elements |

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

One process, two jobs: MCP server talks to your AI agent over stdio, bridge server receives bookmarklet data on port 8899. `peek mcp` runs both.

> Client-side rendering uses [modern-screenshot](https://github.com/qq15725/modern-screenshot) (MIT, vendored at `static/modern-screenshot.js`). If it fails on an exotic page, the bridge falls back to the old Playwright re-fetch automatically. To force fallback globally, set `PEEK_DOM_SNAPSHOT=0`.

## Troubleshooting

**`Playwright Chromium is not installed`**

Run `playwright install chromium`. This downloads the headless browser engine (~150 MB). Only needed once.

**`ERR_CONNECTION_REFUSED` when taking a screenshot**

Your dev server isn't running on that port. Start your dev server first, then ask the agent to screenshot. If you see this repeatedly, make sure the port in your `CLAUDE.md` matches your actual dev server.

**Agent screenshots the wrong port**

Add the `CLAUDE.md` snippet from step 3 above. Without it, the agent will guess.

**Bookmarklet click does nothing**

Peek's bridge server (which the bookmarklet talks to at `localhost:8899`) isn't running. Usually this means Claude Code isn't open — Claude Code is what launches `peek mcp` in the background. Options:

- **Open Claude Code.** Once it starts, it auto-launches `peek mcp`. Reload your page, click the bookmarklet again.
- **Or run `peek mcp` in a terminal manually.** Keep the terminal open while you use Peek. Ctrl+C when done.
- **If you changed the bridge port with `--port`:** re-drag the bookmarklet from `http://localhost:<new-port>` — the bookmarklet has the old port baked in.

To see what state Peek is in, run `peek` with no arguments — it prints install status and tells you what, if anything, to do next.

**`peek: command not found` after install**

If you used `uv tool install peek-mcp`, make sure `~/.local/bin` is in your PATH. Run `uv tool update-shell` to fix it automatically, then open a new terminal.

If you used `pip install peek-mcp`, your Python scripts directory may not be in PATH. Find it with `pip show peek-mcp | grep Location`.

**`No matching distribution found for peek-mcp`**

Your Python is older than 3.10 (common on macOS system Python). Switch to `uv tool install peek-mcp` — uv downloads a compatible Python for you.

**Using Peek from Safari, Firefox, or a different Chrome profile**

The bookmarklet lives in each browser's bookmark bar independently — there's no cross-browser sync. To use it in another browser, open `http://localhost:8899` in that browser and drag the blue "Peek" button to its bookmark bar. One-time setup per browser. The `screenshot` tool itself is browser-agnostic (it uses Playwright's own headless Chromium), so it works regardless of which browser you develop in.

**Screenshot shows a blank or default page instead of what I see**

`screenshot(url)` renders in a fresh headless session with no cookies or session data — it shows what an anonymous visitor would see, not your current view. If your page requires login, upload, or any user interaction to show its real content:

- **Click the Peek bookmarklet** on the page you want captured, then ask the agent to check your selection. The bookmarklet renders your actual browser view to PNG client-side (since v0.5), so post-login / post-upload / post-interaction state is preserved.
- If the bookmarklet capture itself looks off on an unusual page, try `PEEK_DOM_SNAPSHOT=0 peek mcp` to force the old Playwright re-fetch path. Or take an OS screenshot (`Cmd+Shift+4` on macOS) and paste it directly into your chat.

**Agent returns a screenshot that doesn't match what I'm looking at**

`get_user_selection` returns the last bookmarklet capture, which could be from hours or days ago. The metadata includes an `age_seconds` field — if that number is large, the agent should recognize it and fall back to `screenshot(url)`. To force a fresh capture, click the bookmarklet again on your current page.

## Limitations

- **Local/LAN only.** Public URLs are blocked for security (SSRF prevention).
- **`screenshot(url)` is stateless.** It opens a fresh headless browser — no cookies, no login. For your actual session state, use the bookmarklet → `get_user_selection()`.
- **Bookmarklet capture quality depends on the page.** Most CSS renders faithfully; exotic features (WebGL, cross-origin iframes, playing videos) may render with gaps. Set `PEEK_DOM_SNAPSHOT=0` to fall back to the Playwright re-fetch path if needed.
- **Peek does not survive a full page navigation.** If you click a link that loads a new URL (not an in-place SPA route change), the bookmarklet-injected script is gone. Click the bookmarklet again on the new page to re-activate Peek. This is a fundamental property of bookmarklets — switching to a browser extension would remove this limitation (not planned).
- **Captures may contain sensitive data.** Passwords and hidden inputs are redacted, but visible text and screenshots are saved as-is to `~/.peek/captures/`. Peek keeps the 50 most recent captures automatically; older ones are pruned.

## CLI

```bash
peek mcp                  # start everything (recommended)
peek mcp --port 9000      # different bridge port
```

## Requirements

- `uv` (recommended — manages Python for you) or Python 3.10+
- Playwright Chromium (auto-installed by `peek setup`, or run `playwright install chromium` manually)
