"""CLI entry point for UI Inspector."""

import argparse
import sys


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

    # ui-inspector mcp  (placeholder for future MCP server)
    sub.add_parser("mcp", help="Start as MCP server (stdio)")

    args = parser.parse_args()

    if args.command == "serve":
        from .server import app
        import uvicorn
        uvicorn.run(app, host=args.host, port=args.port)
    elif args.command == "mcp":
        print("MCP server not yet implemented. Coming soon.")
        sys.exit(1)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
