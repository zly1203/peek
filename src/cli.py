"""CLI entry point for UI Inspector."""

import argparse
import sys


def _check_playwright():
    """Check that Playwright Chromium is installed. Exit with guidance if not."""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            p.chromium.executable_path
    except Exception:
        print(
            "\nPlaywright Chromium not found.\n"
            "Run this command to install:\n\n"
            "    playwright install chromium\n\n"
            "Then restart ui-inspector.\n",
            file=sys.stderr,
        )
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        prog="ui-inspector",
        description="Let AI agents see your UI — visual inspection bridge for AI coding agents.",
    )
    sub = parser.add_subparsers(dest="command")

    # ui-inspector serve
    serve_parser = sub.add_parser("serve", help="Start the bridge server")
    serve_parser.add_argument("--port", type=int, default=8899, help="Port (default: 8899)")
    serve_parser.add_argument("--host", default="0.0.0.0", help="Host (default: 0.0.0.0)")

    # ui-inspector mcp
    mcp_parser = sub.add_parser("mcp", help="Start as MCP server (stdio)")
    mcp_parser.add_argument("--port", type=int, default=8899, help="Bridge server port (default: 8899)")
    mcp_parser.add_argument("--host", default="0.0.0.0", help="Bridge server host (default: 0.0.0.0)")

    args = parser.parse_args()

    if args.command in ("serve", "mcp"):
        _check_playwright()

    if args.command == "serve":
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
