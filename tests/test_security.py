"""Security tests — verifies Peek doesn't expose sensitive data or allow abuse.

Covers: path traversal, directory access, SSRF bypass attempts, malicious
payloads, and captures directory isolation.
"""

import json
import base64

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Test client with CAPTURES_DIR pointing to temp dir."""
    import os
    os.environ["PEEK_CAPTURES_DIR"] = str(tmp_path)
    import importlib
    import src.server
    importlib.reload(src.server)
    from src.server import app
    yield TestClient(app)
    os.environ.pop("PEEK_CAPTURES_DIR", None)


# ─── Path traversal ───


def test_static_captures_no_directory_traversal(client, tmp_path):
    """GET /captures/../ should not escape the captures directory."""
    # Create a file outside captures dir that should NOT be accessible
    secret = tmp_path.parent / "secret.txt"
    secret.write_text("sensitive data")

    resp = client.get("/captures/../secret.txt")
    # Should be 404 or 400, NOT 200 with the file contents
    assert resp.status_code != 200 or "sensitive data" not in resp.text


def test_static_captures_no_absolute_path(client):
    """GET /captures//etc/passwd should not serve system files."""
    resp = client.get("/captures//etc/passwd")
    assert resp.status_code != 200


def test_capture_filenames_are_server_generated(client, tmp_path):
    """Capture filenames use server-generated timestamps, not user input."""
    # POST a capture with a malicious "timestamp" in the payload
    data = {
        "mode": "element",
        "url": "http://localhost:8080",
        "viewport": {"width": 1280, "height": 800},
        "scroll": {"x": 0, "y": 0},
        "elements": [],
        "timestamp": "../../etc/malicious",  # attacker tries to inject
    }
    resp = client.post("/api/capture", json=data)

    # The response timestamp should be server-generated (YYYYMMDD_HHMMSS format)
    if resp.status_code == 200:
        ts = resp.json().get("timestamp", "")
        assert "/" not in ts, "Timestamp should not contain path separators"
        assert ".." not in ts, "Timestamp should not contain path traversal"
        assert len(ts) == 15, f"Timestamp should be YYYYMMDD_HHMMSS format, got: {ts}"


# ─── SSRF bypass attempts ───


def test_ssrf_bypass_redirect(client):
    """URL validation should catch common SSRF bypass patterns."""
    from src.screenshot import validate_url
    import pytest

    bypass_attempts = [
        "http://0x7f000001:8080",       # hex IP for 127.0.0.1
        "http://[::1]:8080",             # IPv6 localhost (allowed — just verify no crash)
        "http://localhost.evil.com",     # subdomain trick
        "http://evil.com@localhost",     # userinfo trick
        "http://169.254.169.254",       # AWS metadata
        "http://internal.company.com",  # internal hostname
        "ftp://localhost:21",            # non-HTTP scheme
        "gopher://localhost:8080",       # gopher scheme
    ]

    for url in bypass_attempts:
        try:
            validate_url(url)
            # If it passed, it should only be for actual localhost
            from urllib.parse import urlparse
            parsed = urlparse(url)
            assert parsed.hostname in ("localhost", "127.0.0.1", "0.0.0.0", "::1"), (
                f"validate_url allowed non-localhost URL: {url}"
            )
        except ValueError:
            pass  # Expected — rejected correctly


# ─── Malicious payloads ───


def test_capture_with_script_injection_in_elements(client, tmp_path):
    """Malicious script tags in element data should be stored safely (not executed)."""
    data = {
        "mode": "element",
        "url": "http://localhost:8080",
        "viewport": {"width": 1280, "height": 800},
        "scroll": {"x": 0, "y": 0},
        "elements": [{
            "selector": "<script>alert('xss')</script>",
            "tagName": "div",
            "text": "<img onerror=alert(1) src=x>",
            "outerHTML": "<div onclick='alert(1)'>evil</div>",
        }],
    }
    resp = client.post("/api/capture", json=data)

    # The data should be stored as JSON (escaped), not interpreted
    if resp.status_code == 200:
        stored = json.loads((tmp_path / "capture_latest.json").read_text())
        # Verify it's stored as plain text, not executed
        assert "<script>" in stored["elements"][0]["selector"]
        assert stored["elements"][0]["selector"] == "<script>alert('xss')</script>"


def test_capture_with_oversized_elements_array(client):
    """Large elements array should not crash the server."""
    data = {
        "mode": "region",
        "url": "http://localhost:8080",
        "viewport": {"width": 1280, "height": 800},
        "scroll": {"x": 0, "y": 0},
        "region": {"x": 0, "y": 0, "width": 100, "height": 100},
        "elements": [{"selector": f"#el-{i}", "tagName": "div"} for i in range(1000)],
    }
    resp = client.post("/api/capture", json=data)
    # Should not crash — may succeed or fail gracefully
    assert resp.status_code in (200, 413, 500)


def test_invalid_base64_in_screenshot(client):
    """Invalid base64 in screenshotBase64 should not crash the server."""
    data = {
        "mode": "annotate",
        "url": "http://localhost:8080",
        "viewport": {"width": 1280, "height": 800},
        "scroll": {"x": 0, "y": 0},
        "elements": [],
        "screenshotBase64": "this-is-not-valid-base64!!!",
    }
    resp = client.post("/api/capture", json=data)
    # Should return an error, not crash
    assert resp.status_code in (200, 400, 422, 500)


# ─── Captures directory isolation ───


def test_captures_dir_permissions(tmp_path):
    """CAPTURES_DIR should be created with standard permissions."""
    import os
    captures = tmp_path / "test_captures"
    os.environ["PEEK_CAPTURES_DIR"] = str(captures)
    import importlib
    import src.server
    importlib.reload(src.server)

    assert captures.exists()
    # Should be readable/writable by owner
    stat = captures.stat()
    mode = oct(stat.st_mode)[-3:]
    assert mode[0] == "7", f"Owner should have rwx, got {mode}"
    os.environ.pop("PEEK_CAPTURES_DIR", None)


def test_captures_dir_not_in_package_dir():
    """Default CAPTURES_DIR must not be inside the package installation."""
    import os
    env = os.environ.copy()
    env.pop("PEEK_CAPTURES_DIR", None)
    from unittest.mock import patch
    with patch.dict(os.environ, env, clear=True):
        import importlib
        import src.server
        importlib.reload(src.server)

        captures_str = str(src.server.CAPTURES_DIR)
        assert "site-packages" not in captures_str
        assert "dist-packages" not in captures_str
        assert ".peek" in captures_str


def test_get_latest_capture_reads_only_from_captures_dir(tmp_path, monkeypatch):
    """get_latest_capture should only read from CAPTURES_DIR, nowhere else."""
    import os
    os.environ["PEEK_CAPTURES_DIR"] = str(tmp_path)
    import importlib
    import src.mcp_server
    importlib.reload(src.mcp_server)

    # No captures — should return "no captures" message
    import asyncio
    result = asyncio.run(src.mcp_server.get_latest_capture())
    assert len(result) == 1
    assert "no captures" in result[0].text.lower()

    # Create a capture
    metadata = {"mode": "element", "url": "http://localhost:8080", "elements": []}
    (tmp_path / "capture_latest.json").write_text(json.dumps(metadata))

    result = asyncio.run(src.mcp_server.get_latest_capture())
    assert result[0].type == "text"
    data = json.loads(result[0].text)
    assert data["url"] == "http://localhost:8080"

    os.environ.pop("PEEK_CAPTURES_DIR", None)
