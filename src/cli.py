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


def _add_claude_mcp():
    """Add peek as a Claude Code MCP server (user scope)."""
    peek_path = shutil.which("peek")
    if not peek_path:
        return False, "peek binary not found in PATH"
    try:
        # Check if already added with correct path
        list_result = subprocess.run(
            ["claude", "mcp", "list"],
            capture_output=True, text=True, timeout=10,
        )
        if "peek" in (list_result.stdout or ""):
            # Verify the registered path matches current peek binary
            if peek_path in (list_result.stdout or ""):
                return True, "already configured"
            # Path mismatch — re-register with correct path
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
    """Run the one-shot setup wizard."""
    print()
    print("  Peek setup")
    print("  ──────────")
    print()

    # Step 1: Playwright
    print("  [1/3] Checking Playwright Chromium...")
    if _check_playwright():
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
