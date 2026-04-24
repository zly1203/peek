"""CLI entry point for Peek."""

import argparse
import os
import shutil
import subprocess
import sys
import webbrowser


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
    """Run the one-shot setup wizard. Detects already-installed state and
    short-circuits, so users who run `peek setup` on an upgrade don't get
    walked through the drag-the-bookmarklet flow again."""
    print()
    print("  Peek setup")
    print("  ──────────")
    print()

    playwright_ok = _check_playwright()
    claude_ok = _detect_claude_code() and _claude_mcp_registered_correctly()

    # Fast path: everything already in place. Don't open a browser, don't
    # start the MCP server, don't re-print the drag instructions. Just
    # confirm state and exit.
    if playwright_ok and claude_ok:
        print("  ✓ Already set up")
        print("    • Playwright Chromium: installed")
        print("    • Claude Code MCP: registered (mcp subcommand, correct binary path)")
        print()
        print("  Nothing to do. Your existing bookmarklet works as-is (from v0.5+).")
        print("  If you need to (re)grab the bookmarklet, open http://localhost:8899")
        print("  while Peek is running (`peek mcp` or via Claude Code).")
        print()
        return

    # First-time install (or partial install) — run the wizard.
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

    # Step 3: Bookmarklet
    print("\n  [3/3] Setting up bookmarklet...")
    print("        Opening http://localhost:8899 in your browser")
    print("        Drag the blue 'Peek' button to your bookmark bar.\n")

    # Add CLAUDE.md hint
    print("  Recommended: add this to your project's CLAUDE.md so AI knows your dev port:")
    print()
    print("    Dev server runs on http://localhost:3000")
    print("    When using Peek's screenshot tool, ask me which port the app is")
    print("    running on if you don't know.")
    print()
    print("  Starting peek mcp now (Ctrl+C to stop)...\n")

    # Open browser then start server
    try:
        webbrowser.open("http://localhost:8899")
    except Exception:
        pass

    from .mcp_server import run
    run()


def main():
    parser = argparse.ArgumentParser(
        prog="peek",
        description="Let AI agents see your UI — visual inspection bridge for AI coding agents.",
    )
    sub = parser.add_subparsers(dest="command")

    # peek setup
    sub.add_parser("setup", help="One-command setup: Playwright + Claude Code MCP + open bookmarklet page")

    # peek serve
    serve_parser = sub.add_parser("serve", help="Start the bridge server")
    serve_parser.add_argument("--port", type=int, default=8899, help="Port (default: 8899)")
    serve_parser.add_argument("--host", default="127.0.0.1", help="Host (default: 127.0.0.1)")

    # peek mcp
    mcp_parser = sub.add_parser("mcp", help="Start as MCP server (stdio)")
    mcp_parser.add_argument("--port", type=int, default=8899, help="Bridge server port (default: 8899)")
    mcp_parser.add_argument("--host", default="127.0.0.1", help="Bridge server host (default: 127.0.0.1)")

    args = parser.parse_args()

    if args.command in ("serve", "mcp"):
        _ensure_playwright()

    if args.command == "setup":
        _setup()
    elif args.command == "serve":
        from .server import app
        import uvicorn
        uvicorn.run(app, host=args.host, port=args.port)
    elif args.command == "mcp":
        from .mcp_server import run
        run(host=args.host, port=args.port)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
