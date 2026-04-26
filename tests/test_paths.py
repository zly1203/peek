"""Tests for critical path resolution — prevents CAPTURES_DIR bugs.

These verify that CAPTURES_DIR, STATIC_DIR, and env var overrides resolve
correctly regardless of where the package is installed.
"""

import os
from pathlib import Path
from unittest.mock import patch

import pytest


def test_default_captures_dir_is_in_user_home():
    """Default CAPTURES_DIR should be ~/.peek/captures/, not in site-packages."""
    import importlib
    # Remove env var override if present
    env = os.environ.copy()
    env.pop("PEEK_CAPTURES_DIR", None)
    with patch.dict(os.environ, env, clear=True):
        import src.server
        importlib.reload(src.server)
        captures = src.server.CAPTURES_DIR

        assert ".peek" in str(captures), f"CAPTURES_DIR should contain .peek, got {captures}"
        assert "site-packages" not in str(captures), f"CAPTURES_DIR should not be in site-packages, got {captures}"
        assert str(captures).startswith(str(Path.home())), f"CAPTURES_DIR should be under home dir, got {captures}"


def test_server_and_mcp_captures_dir_match():
    """server.py and mcp_server.py must resolve to the same CAPTURES_DIR."""
    import importlib
    env = os.environ.copy()
    env.pop("PEEK_CAPTURES_DIR", None)
    with patch.dict(os.environ, env, clear=True):
        import src.server
        import src.mcp_server
        importlib.reload(src.server)
        importlib.reload(src.mcp_server)

        assert src.server.CAPTURES_DIR == src.mcp_server.CAPTURES_DIR, (
            f"server={src.server.CAPTURES_DIR}, mcp={src.mcp_server.CAPTURES_DIR}"
        )


def test_captures_dir_env_var_override():
    """PEEK_CAPTURES_DIR env var should override the default."""
    import importlib
    with patch.dict(os.environ, {"PEEK_CAPTURES_DIR": "/tmp/test-peek-captures"}):
        import src.server
        importlib.reload(src.server)

        assert str(src.server.CAPTURES_DIR) == "/tmp/test-peek-captures"


def test_captures_dir_auto_creates(tmp_path):
    """CAPTURES_DIR should auto-create with parent directories."""
    import importlib
    deep_path = str(tmp_path / "a" / "b" / "captures")
    with patch.dict(os.environ, {"PEEK_CAPTURES_DIR": deep_path}):
        import src.server
        importlib.reload(src.server)

        assert Path(deep_path).exists(), "CAPTURES_DIR should auto-create nested dirs"


def test_static_dir_contains_inspector_js():
    """STATIC_DIR should contain inspector.js (verifies wheel packaging)."""
    from src.server import STATIC_DIR

    js_path = STATIC_DIR / "inspector.js"
    assert js_path.exists(), f"inspector.js not found at {js_path}"
    content = js_path.read_text()
    assert "__inspectorActive" in content, "inspector.js should contain __inspectorActive"


# ─── Production environment tests ───


def test_inspector_js_has_bridge_override():
    """inspector.js must support window.__PEEK_BRIDGE_URL override."""
    from src.server import STATIC_DIR

    content = (STATIC_DIR / "inspector.js").read_text()
    assert "__PEEK_BRIDGE_URL" in content, (
        "inspector.js must read window.__PEEK_BRIDGE_URL for port override"
    )


def test_inspector_js_bridge_default_is_8899():
    """Default BRIDGE URL should be localhost:8899."""
    from src.server import STATIC_DIR

    content = (STATIC_DIR / "inspector.js").read_text()
    assert "localhost:8899" in content, "Default BRIDGE should be localhost:8899"


def test_setup_page_bookmarklet_loads_inspector():
    """Setup page HTML should load inspector.js from bridge server."""
    from src.server import SETUP_HTML

    assert "inspector.js" in SETUP_HTML, "Setup page should reference inspector.js"
    assert "localhost:8899" in SETUP_HTML, "Bookmarklet should point to default bridge port"


def test_cli_entry_point_exists():
    """The 'peek' CLI entry point should be importable."""
    from src.cli import main
    assert callable(main)


def test_mcp_tools_registered():
    """MCP server should have screenshot and get_user_selection tools."""
    from src.mcp_server import mcp

    tool_names = [t.name for t in mcp._tool_manager.list_tools()]
    assert "screenshot" in tool_names, "screenshot tool not registered"
    assert "get_user_selection" in tool_names, "get_user_selection tool not registered"


def test_screenshot_url_validation():
    """validate_url accepts localhost + file://, rejects external + non-
    http(s)/file schemes. file:// was added as a permitted scheme in
    v0.5.13 (see test_validate_url_allows_file_scheme in test_screenshot.py)."""
    from src.screenshot import validate_url

    # Should pass
    validate_url("http://localhost:3000")
    validate_url("http://127.0.0.1:8080")
    validate_url("file:///Users/me/page.html")

    # Should reject
    with pytest.raises(ValueError, match="localhost"):
        validate_url("http://google.com")
    with pytest.raises(ValueError, match="scheme"):
        validate_url("javascript:alert(1)")


def test_cors_allows_only_localhost():
    """CORS middleware should only allow localhost origins."""
    import re
    from src.server import app

    # Find CORS middleware config
    cors_middleware = None
    for m in app.user_middleware:
        if "CORS" in str(m):
            cors_middleware = m
            break

    assert cors_middleware is not None, "CORS middleware not found"
    regex = cors_middleware.kwargs.get("allow_origin_regex", "")
    assert regex, "CORS should have allow_origin_regex"
    # localhost should match
    assert re.match(regex, "http://localhost:3000")
    assert re.match(regex, "http://127.0.0.1:8080")
    # External should NOT match
    assert not re.match(regex, "http://evil.com")
    assert not re.match(regex, "http://google.com")
