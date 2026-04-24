"""CLI entry point for Peek."""

import argparse
import os
import shutil
import subprocess
import sys
import webbrowser
from pathlib import Path


PEEK_DIR = Path.home() / ".peek"
BOOKMARKLET_FILE = PEEK_DIR / "bookmarklet.html"


def _write_bookmarklet_file() -> Path:
    """Write the bookmarklet HTML to ~/.peek/bookmarklet.html and return its path.
    The file is self-contained — no server needed to view or drag from it."""
    from .server import SETUP_HTML
    PEEK_DIR.mkdir(parents=True, exist_ok=True)
    BOOKMARKLET_FILE.write_text(SETUP_HTML)
    return BOOKMARKLET_FILE


def _open_bookmarklet_page():
    """Write the bookmarklet HTML locally and open it in the default browser.
    Returns True on success."""
    try:
        path = _write_bookmarklet_file()
        webbrowser.open(path.as_uri())
        return True
    except Exception as e:
        print(f"  Failed to open bookmarklet page: {e}", file=sys.stderr)
        return False


def _check_playwright(verbose: bool = False):
    """Check that Playwright Chromium is installed. Return True if installed."""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            if not os.path.exists(p.chromium.executable_path):
                raise FileNotFoundError("Chromium binary not found")
        return True
    except Exception:
        if verbose:
            print(
                "\nPlaywright Chromium not found.\n"
                "Run this command to install:\n\n"
                "    playwright install chromium\n\n"
                "Then restart peek.\n",
                file=sys.stderr,
            )
        return False


def _ensure_playwright():
    """Check Playwright; exit with guidance if missing."""
    if not _check_playwright(verbose=True):
        sys.exit(1)


def _install_playwright():
    """Try to install Playwright Chromium. Return True on success."""
    print("Installing Playwright Chromium (~150 MB, one-time)...")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            check=True,
        )
        return result.returncode == 0
    except Exception as e:
        print(f"  Failed: {e}", file=sys.stderr)
        return False


def _detect_claude_code():
    """Check if Claude Code CLI is installed."""
    return shutil.which("claude") is not None


def _claude_mcp_line_for_peek():
    """Return the `claude mcp list` line that mentions `peek`, or None.

    Used for state detection — if the line mentions the current peek binary
    AND ` mcp` as the subcommand, the registration is good."""
    try:
        result = subprocess.run(
            ["claude", "mcp", "list"],
            capture_output=True, text=True, timeout=10,
        )
        for line in (result.stdout or "").splitlines():
            if "peek" in line:
                return line
    except Exception:
        pass
    return None


def _claude_mcp_registered_correctly():
    """True iff Claude Code has `peek` registered with current binary + `mcp` subcommand."""
    peek_path = shutil.which("peek")
    if not peek_path:
        return False
    line = _claude_mcp_line_for_peek()
    if not line or peek_path not in line:
        return False
    # After the binary path, the subcommand should be `mcp`. Older versions
    # accidentally registered `peek setup`, which is the root cause of the
    # "bookmarklet page keeps opening after upgrade" bug.
    rest = line.split(peek_path, 1)[1]
    return "mcp" in rest.split() or rest.lstrip().startswith("mcp")


def _add_claude_mcp():
    """Add peek as a Claude Code MCP server (user scope)."""
    peek_path = shutil.which("peek")
    if not peek_path:
        return False, "peek binary not found in PATH"
    try:
        if _claude_mcp_registered_correctly():
            return True, "already configured"

        # If there's a stale `peek` entry (wrong path, or registered with the
        # wrong subcommand like `setup`), remove it before re-adding.
        if _claude_mcp_line_for_peek():
            subprocess.run(
                ["claude", "mcp", "remove", "-s", "user", "peek"],
                capture_output=True, text=True, timeout=10,
            )

        result = subprocess.run(
            ["claude", "mcp", "add", "-s", "user", "peek", "--", peek_path, "mcp"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0:
            return True, "added"
        return False, (result.stderr or result.stdout or "unknown error").strip()
    except Exception as e:
        return False, str(e)


def _setup():
    """One-shot setup: install Playwright, register Claude Code MCP, drop the
    bookmarklet HTML locally and open it in the browser. Then exit. No
    long-running server — `peek setup` runs and returns like `npm install`."""
    print()
    print("  Peek setup")
    print("  ──────────")
    print()

    playwright_ok = _check_playwright()
    claude_ok = _detect_claude_code() and _claude_mcp_registered_correctly()

    # Fast path: everything already in place. Reopen the local bookmarklet
    # file in case that's why the user invoked setup, then exit.
    if playwright_ok and claude_ok:
        print("  ✓ Already set up")
        print("    • Playwright Chromium: installed")
        print("    • Claude Code MCP: registered")
        print()
        print("  Nothing to do. Close this terminal and use Claude Code as usual —")
        print("  it'll launch peek in the background when an agent needs it.")
        print()
        print(f"  Need the bookmarklet again? {BOOKMARKLET_FILE} is always there —")
        print("  opening it now in your browser.")
        _open_bookmarklet_page()
        print()
        return

    # Step 1: Playwright
    print("  [1/3] Checking Playwright Chromium...")
    if playwright_ok:
        print("        OK — Chromium installed")
    else:
        print("        Not found — installing...")
        if not _install_playwright():
            print("\n        Install failed. Try manually:")
            print("          playwright install chromium\n", file=sys.stderr)
            sys.exit(1)
        print("        OK — Chromium installed")

    # Step 2: Claude Code MCP
    print("\n  [2/3] Checking Claude Code...")
    if not _detect_claude_code():
        print("        Claude Code CLI not found — skipping MCP setup")
        print("        (For other tools like Cursor, see README for manual config)")
    else:
        print("        Found — adding Peek as MCP server (user scope)...")
        ok, msg = _add_claude_mcp()
        if ok:
            print(f"        OK — {msg}")
        else:
            print(f"        Failed — {msg}")
            print("        You can add it manually later:")
            print("          claude mcp add -s user peek -- $(which peek) mcp")

    # Step 3: bookmarklet page — local file, no server needed.
    print("\n  [3/3] Opening bookmarklet page in your browser...")
    path = _write_bookmarklet_file()
    print(f"        {path}")
    print("        Drag the blue 'Peek' button to your bookmark bar.")
    try:
        webbrowser.open(path.as_uri())
    except Exception:
        pass

    # Optional CLAUDE.md hint
    print()
    print("  Recommended: add this to your project's CLAUDE.md so the agent")
    print("  knows your dev port:")
    print()
    print("    Dev server runs on http://localhost:3000")
    print("    When using Peek's screenshot tool, ask me which port the app is")
    print("    running on if you don't know.")
    print()
    print("  ──────────────────────────────────────────────────────────────")
    print("  Setup complete. You can close this terminal.")
    print()
    if _detect_claude_code():
        print("  From here on: open Claude Code and use it normally — it'll")
        print("  launch peek in the background whenever an agent uses a Peek")
        print("  tool. No `peek` command needs to keep running.")
    else:
        print("  From here on: point your MCP client (Cursor / Windsurf /")
        print("  Claude Desktop) at `peek mcp` — see README for the config")
        print("  snippet. Or, if you just want to try the bookmarklet without")
        print("  an agent, run `peek mcp` in a terminal and keep it open.")
    print("  ──────────────────────────────────────────────────────────────")
    print()


def _print_status_and_next_steps():
    """Default output when someone runs `peek` with no subcommand.
    Detects install state and tells the user what, if anything, to do next.
    More useful than argparse's auto-generated help for non-CLI-savvy users."""
    try:
        from . import __version__ as version  # type: ignore
    except Exception:
        version = None

    # Read version from pyproject if possible (editable install fallback)
    if version is None:
        try:
            import importlib.metadata
            version = importlib.metadata.version("peek-mcp")
        except Exception:
            version = "?"

    playwright_ok = _check_playwright()
    claude_installed = _detect_claude_code()
    claude_registered = claude_installed and _claude_mcp_registered_correctly()

    print()
    print(f"  Peek {version} — status")
    print("  " + "─" * 32)
    print()
    print(f"    Playwright Chromium : {'✓ installed' if playwright_ok else '✗ not installed'}")
    if claude_installed:
        print(f"    Claude Code MCP     : {'✓ registered' if claude_registered else '✗ not registered'}")
    else:
        print( "    Claude Code         : not detected (optional — see README for Cursor/Windsurf/etc.)")
    print()

    if playwright_ok and claude_registered:
        print("  ✓ Peek is ready. You don't need to run any peek command.")
        print()
        print("    • Using Claude Code? Just open it and ask the agent to screenshot a")
        print("      page or check your bookmarklet selection. Peek auto-launches.")
        if BOOKMARKLET_FILE.exists():
            print(f"    • Need the bookmarklet again? Open {BOOKMARKLET_FILE}")
            print("      in your browser and drag the blue button to your bookmark bar.")
        else:
            print("    • First time? Run `peek setup` to get the bookmarklet page.")
    elif not playwright_ok or (claude_installed and not claude_registered):
        print("  → Run `peek setup` to finish configuring Peek.")
    else:
        # Playwright ok, Claude Code absent — user has another MCP client
        print("  Peek's Python side is installed. For Claude Code users: run")
        print("  `peek setup` to auto-register the MCP server. For other tools")
        print("  (Cursor / Windsurf / Claude Desktop), see the README for the")
        print("  MCP config snippet — the `command` value is `" + (shutil.which("peek") or "peek") + "` with `[\"mcp\"]` args.")

    print()
    print("  Run `peek --help` to see all subcommands (most are advanced).")
    print()


def main():
    parser = argparse.ArgumentParser(
        prog="peek",
        description="Let AI agents see your UI — visual inspection bridge for AI coding agents.",
        epilog="Run `peek` with no arguments to see install status and next steps.",
    )
    sub = parser.add_subparsers(dest="command")

    # peek setup
    sub.add_parser(
        "setup",
        help="First-time setup: install Playwright Chromium, register the Claude Code MCP server, open the bookmarklet page. Safe to re-run on an already-configured machine (it detects state and exits).",
    )

    # peek mcp
    mcp_parser = sub.add_parser(
        "mcp",
        help="Start the MCP server (stdio). Advanced — Claude Code (and most MCP clients) launch this for you automatically, so you rarely need to run it by hand.",
    )
    mcp_parser.add_argument("--port", type=int, default=8899, help="Bridge server port (default: 8899)")
    mcp_parser.add_argument("--host", default="127.0.0.1", help="Bridge server host (default: 127.0.0.1)")

    args = parser.parse_args()

    if args.command == "mcp":
        _ensure_playwright()

    if args.command == "setup":
        _setup()
    elif args.command == "mcp":
        from .mcp_server import run
        run(host=args.host, port=args.port)
    else:
        _print_status_and_next_steps()


if __name__ == "__main__":
    main()
