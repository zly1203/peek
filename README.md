# Peek

Point at your UI. Your AI agent sees it.

<p align="center">
  <img src="peek-demo.gif" alt="Peek demo: point at a UI element, agent sees it" width="720">
</p>

## Why

AI coding agents can edit code, but they can't see your page. You end up describing layouts in words, copy-pasting HTML, or dragging screenshots into chat.

Peek fixes this. Your AI agent can screenshot any local page on its own. You can also point at specific elements with a bookmarklet, and the agent gets the screenshot plus element data (selectors, styles, bounding boxes).

## Contents

- [Quick Start](#quick-start)
  - [Claude Code (CLI or VS Code)](#claude-code-cli-or-vs-code)
  - [Upgrading](#upgrading)
  - [Other MCP clients (experimental)](#other-mcp-clients-experimental)
  - [Tell your agent your dev port](#recommended-tell-your-agent-your-dev-port)
  - [Use it](#use-it)
- [Supported URLs](#supported-urls)
- [MCP Tools](#mcp-tools)
- [How It Works](#how-it-works)
- [Troubleshooting](#troubleshooting)
- [Limitations](#limitations)
- [CLI](#cli)

## Quick Start

### Claude Code (CLI or VS Code)

```bash
# 1. Install uv (one-time, manages Python for you)
brew install uv
# or: curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. Install peek (uv auto-downloads a compatible Python)
uv tool install peek-mcp

# 3. One-shot setup
peek setup
```

`peek setup` is one-shot: installs Playwright Chromium, registers Peek as an MCP server in Claude Code (user scope, all projects), drops the bookmarklet page at `~/.peek/bookmarklet.html` and opens it in your browser. Drag the blue button to your bookmark bar and you're done; the command exits on its own. Nothing to keep running.

From then on: **open Claude Code and use it normally.** It auto-launches Peek in the background whenever the agent uses a Peek tool.

> Using pip directly? `pip install peek-mcp` works too, but requires Python 3.10+ already installed. `uv tool install` avoids the version-mismatch headache.

### Upgrading

```bash
uv tool upgrade peek-mcp
```

That's it. The next time Claude Code launches `peek mcp` it'll pick up the new version. Open browser tabs with an old `inspector.js` auto-take-over on the next bookmarklet click.

### Other MCP clients (experimental)

> **Heads-up:** Peek is currently developed and tested against Claude Code. It implements the standard MCP protocol so it *should* work with Cursor / Windsurf / Claude Desktop / any MCP-compatible client, but those paths are not actively battle-tested. Issue reports welcome.

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

Run `which peek` in your terminal to get the absolute path. Drag the bookmarklet from `~/.peek/bookmarklet.html` (`peek setup` creates it). No server needed.

### Recommended: tell your agent your dev port

Add this to your project's `CLAUDE.md` (or `.cursorrules`, etc.):

```
Dev server runs on http://localhost:3000

When using Peek's screenshot tool and you don't know the dev server URL, ask me which port the app is running on before taking a screenshot.
```

Replace `3000` with your actual port. **This prevents your agent from guessing the wrong port.**

### Use it

Two paths: point at something in your real browser (the main one), or have the agent take a headless screenshot (handy for verifying its own fix). Mix as needed.

> **Tip:** to guarantee Peek gets invoked, prefix your request with *"use the Peek MCP tool to ..."*. The agent's auto-tool-selection is usually reliable, but the explicit form removes any ambiguity, especially right after install when you're not sure Peek is wired up correctly.

**1) User-pointed captures**

1. One-time: drag the blue button from `~/.peek/bookmarklet.html` to your bookmark bar
2. Open your app, click the bookmarklet, pick a mode:

| Mode | Shortcut | You do | Agent gets |
|------|----------|--------|------------|
| **Region** | `Alt+R` | Drag a rectangle | Screenshot + elements in that area |
| **Element** | `Alt+S` | Click an element | Screenshot + selector, styles, HTML |
| **Annotate** | `Alt+A` | Draw freehand | Screenshot + your drawings + elements |

3. Tell your agent. A **copy-paste-ready first prompt** covers everything the agent needs (which app, that you used Peek, what's wrong):

> *"I'm working on http://localhost:3000. Use the Peek MCP tool to check the UI element I just selected. This card overlaps the sidebar on hover."*

Once the agent knows your port (or you've added it to your `CLAUDE.md`), you can drop the prefix:

- *"Use the Peek MCP tool to look at what I selected and make the spacing match the cards above."*
- *"I annotated the layout issues with Peek. Fix them."*

The agent calls `get_user_selection()` and receives your capture (PNG + element metadata) as its source of truth.

**2) Agent-driven screenshots (verification or self-check)**

After path 1 sends an issue, you usually want the agent to **verify its fix**. Or sometimes you just want a headless render of a public-ish route without leaving your editor. That's what `screenshot(url)` is for:

- *"Use the Peek MCP tool to screenshot http://localhost:3000/checkout and verify the button renders correctly now."* ← typical post-fix loop
- *"Take a Peek screenshot of localhost:3000 and tell me if the layout looks right on a fresh load."* ← pre-fix sanity check
- *"I just renamed the header. Use Peek to screenshot the page and confirm it updated."* ← quick visual diff

This path is stateless: a fresh headless browser opens, renders the URL, closes. Logged-in views, uploaded data, hovered states are NOT visible this way; for those, use path 1. (This is also why path 1 is the main one: it captures *your* real browser state, not a clean stranger's.)

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
| `screenshot(url)` | **Default**. Agent fetches any local/LAN URL in a fresh headless browser. Use for general "look at the page" requests, verifying code changes, etc. |
| `get_user_selection()` | Reads what *you* captured with the bookmarklet: a region, element, or annotation. Use when you want the agent to see exactly what you pointed at, including any state that requires your interaction (login, uploaded data, clicked buttons). |

For `Element` mode captures, the agent gets structural context to find the right code:

- **ancestor chain** (`body > main > section.settings > div.flex`)
- **sibling position** (`2 of 3 <button> siblings`)
- **nearest heading** (`h2: Settings`)
- **parent layout** (`flex, row`)

This means when you point at a button, the agent knows *which* button on which section. No guessing.

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

Client-side rendering uses [modern-screenshot](https://github.com/qq15725/modern-screenshot) (MIT, vendored). If it fails on an exotic page, you'll see a red error toast; click Send again or pick a smaller selection. (Earlier versions silently fell back to a fresh Playwright fetch on render error, but that loses your logged-in/JS-modified state, which is the whole point of the client-side path.) To globally force the Playwright path anyway, set `PEEK_DOM_SNAPSHOT=0`.

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

Your Python is older than 3.10 (common on macOS system Python). Switch to `uv tool install peek-mcp`; uv downloads a compatible Python for you.

**Using Peek from Safari, Firefox, or a different Chrome profile**

Open `~/.peek/bookmarklet.html` in that browser and drag the blue button to its bookmark bar (one-time setup per browser). The `screenshot` tool itself is browser-agnostic (headless Chromium), so it works regardless of your dev browser.

**Screenshot shows a blank or default page instead of what I see**

`screenshot(url)` runs a fresh headless browser, with no cookies, no login, no interaction state. For pages behind login / upload / button clicks, use the bookmarklet → `get_user_selection()` instead; it captures your real browser view. If that too looks wrong on an unusual page, try `PEEK_DOM_SNAPSHOT=0` to fall back to Playwright.

**Agent returns a stale screenshot**

`get_user_selection` returns the last bookmarklet capture. Click the bookmarklet again on your current page to refresh it.

## Limitations

- **Local/LAN only.** Public URLs are blocked (SSRF prevention).
- **Bookmarklet render quality varies.** WebGL, cross-origin iframes, and playing videos may not capture faithfully; set `PEEK_DOM_SNAPSHOT=0` to fall back to Playwright.
- **Peek doesn't survive full-page navigation.** Click a link to a new URL and the bookmarklet script is gone. Click the bookmarklet again on the new page. Bookmarklet architecture constraint.
- **Captures may contain sensitive data.** Passwords and hidden inputs are redacted, but visible text + screenshots live at `~/.peek/captures/` (last 50 kept, older pruned).

## CLI

```bash
peek                      # status + next step (most users just need this)
peek setup                # one-shot: install, register MCP, drop bookmarklet page
peek mcp                  # advanced; your MCP client auto-launches this
peek mcp --port 9000      # advanced; different bridge port
```

### When do I need to run `peek mcp` manually?

Almost never. Claude Code auto-launches `peek mcp` whenever an agent uses a Peek tool (registered by `peek setup`).

If you've configured Peek for another MCP client (see "Other MCP clients" above), that client should launch it the same way per the standard MCP spec, but that path isn't actively tested.

The one case you'd run `peek mcp` by hand: **testing the bookmarklet without any MCP client in the loop**. E.g. drawing on a page just to see what data Peek sends. Keep the terminal open while you test; Ctrl+C to stop.
