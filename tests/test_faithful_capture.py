"""Tests for the v0.5 faithful-capture path:
- client-side PNG preferred when pageScreenshotBase64 is present
- Playwright fallback when absent or when PEEK_DOM_SNAPSHOT=0
- Capture archive is pruned to MAX_TIMESTAMPED_CAPTURES
"""

import base64
import os
from unittest.mock import AsyncMock, patch
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client_with_mock():
    """TestClient with Playwright-fallback screenshot mocked out."""
    with patch("src.server.async_playwright") as mock_pw_cls:
        mock_pw = AsyncMock()
        mock_browser = AsyncMock()
        mock_pw.chromium.launch = AsyncMock(return_value=mock_browser)
        mock_pw_cls.return_value.start = AsyncMock(return_value=mock_pw)

        with patch("src.server.playwright_screenshot", new_callable=AsyncMock) as mock_screenshot:
            mock_screenshot.return_value = b"playwright_fallback_png"

            from src.server import app
            with TestClient(app) as c:
                yield c, mock_screenshot


def test_client_png_saved_directly_when_present(client_with_mock):
    """When bookmarklet sends pageScreenshotBase64, bridge saves it verbatim
    and does NOT call Playwright."""
    c, mock_playwright = client_with_mock
    from src.server import CAPTURES_DIR

    client_png = b"\x89PNG\r\n\x1a\n" + b"fake_client_side_content"
    payload = {
        "mode": "region",
        "url": "http://localhost:3000",
        "viewport": {"width": 1280, "height": 800},
        "scroll": {"x": 0, "y": 0},
        "region": {"x": 0, "y": 0, "width": 400, "height": 300},
        "elements": [],
        "pageScreenshotBase64": base64.b64encode(client_png).decode(),
    }

    resp = c.post("/api/capture", json=payload)
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

    # Playwright fallback must not have been invoked
    mock_playwright.assert_not_called()

    # The saved PNG must be byte-identical to what the client sent
    assert (CAPTURES_DIR / "capture_latest.png").read_bytes() == client_png


def test_playwright_fallback_when_no_client_png(client_with_mock):
    """When bookmarklet does NOT send pageScreenshotBase64, bridge falls back
    to the v0.4 Playwright re-fetch."""
    c, mock_playwright = client_with_mock
    from src.server import CAPTURES_DIR

    payload = {
        "mode": "element",
        "url": "http://localhost:3000",
        "viewport": {"width": 1280, "height": 800},
        "scroll": {"x": 0, "y": 0},
        "elements": [{"selector": "h1", "tagName": "h1", "text": "x"}],
    }
    resp = c.post("/api/capture", json=payload)
    assert resp.status_code == 200

    mock_playwright.assert_called_once()
    assert (CAPTURES_DIR / "capture_latest.png").read_bytes() == b"playwright_fallback_png"


def test_env_flag_forces_fallback_even_with_client_png(client_with_mock, monkeypatch):
    """PEEK_DOM_SNAPSHOT=0 forces Playwright fallback even when a client PNG
    is present. Escape hatch for users hitting modern-screenshot bugs."""
    c, mock_playwright = client_with_mock
    from src.server import CAPTURES_DIR

    monkeypatch.setenv("PEEK_DOM_SNAPSHOT", "0")

    payload = {
        "mode": "region",
        "url": "http://localhost:3000",
        "viewport": {"width": 1280, "height": 800},
        "scroll": {"x": 0, "y": 0},
        "region": {"x": 0, "y": 0, "width": 100, "height": 100},
        "elements": [],
        "pageScreenshotBase64": base64.b64encode(b"should_be_ignored").decode(),
    }

    resp = c.post("/api/capture", json=payload)
    assert resp.status_code == 200

    # Playwright WAS called because snapshot path is disabled
    mock_playwright.assert_called_once()
    assert (CAPTURES_DIR / "capture_latest.png").read_bytes() == b"playwright_fallback_png"


def test_base64_raw_not_persisted_in_json(client_with_mock):
    """The raw pageScreenshotBase64 blob must not leak into the saved JSON
    metadata (it would bloat the file and duplicate data on disk)."""
    import json
    c, _ = client_with_mock
    from src.server import CAPTURES_DIR

    payload = {
        "mode": "region",
        "url": "http://localhost:3000",
        "viewport": {"width": 1280, "height": 800},
        "scroll": {"x": 0, "y": 0},
        "region": {"x": 0, "y": 0, "width": 100, "height": 100},
        "elements": [],
        "pageScreenshotBase64": base64.b64encode(b"tiny_png_bytes_here").decode(),
    }
    c.post("/api/capture", json=payload)

    saved = json.loads((CAPTURES_DIR / "capture_latest.json").read_text())
    assert "pageScreenshotBase64" not in saved


def test_prune_keeps_last_n_captures(tmp_path, monkeypatch):
    """_prune_capture_archive deletes older groups beyond the limit;
    capture_latest.* is always preserved."""
    import src.server as server_mod
    monkeypatch.setattr(server_mod, "CAPTURES_DIR", tmp_path)

    # Seed 5 timestamped captures plus latest
    for i in range(5):
        ts = f"2026042{i}_120000"
        (tmp_path / f"capture_{ts}.json").write_text("{}")
        (tmp_path / f"capture_{ts}.png").write_bytes(b"x")
    (tmp_path / "capture_latest.json").write_text("{}")
    (tmp_path / "capture_latest.png").write_bytes(b"y")

    # Prune to keep only 2
    server_mod._prune_capture_archive(max_captures=2)

    remaining_ts = sorted(
        f.name for f in tmp_path.iterdir()
        if f.name.startswith("capture_") and not f.name.startswith("capture_latest")
    )
    # Newest 2 groups survive: 20260424_* and 20260423_*
    assert any("20260424" in n for n in remaining_ts)
    assert any("20260423" in n for n in remaining_ts)
    # Older groups gone
    assert not any("20260420" in n for n in remaining_ts)
    assert not any("20260421" in n for n in remaining_ts)
    assert not any("20260422" in n for n in remaining_ts)
    # latest always preserved
    assert (tmp_path / "capture_latest.json").exists()
    assert (tmp_path / "capture_latest.png").exists()


def test_prune_handles_annot_files(tmp_path, monkeypatch):
    """Annotate-mode files (capture_{ts}_annot.png) are grouped with their ts
    and deleted together."""
    import src.server as server_mod
    monkeypatch.setattr(server_mod, "CAPTURES_DIR", tmp_path)

    for i in range(3):
        ts = f"2026042{i}_120000"
        (tmp_path / f"capture_{ts}.json").write_text("{}")
        (tmp_path / f"capture_{ts}.png").write_bytes(b"x")
        (tmp_path / f"capture_{ts}_annot.png").write_bytes(b"a")

    server_mod._prune_capture_archive(max_captures=1)

    remaining = [f.name for f in tmp_path.iterdir()]
    # Only the newest ts's files survive (3 files for that ts: json, png, annot.png)
    newest_files = [n for n in remaining if "20260422" in n]
    assert len(newest_files) == 3
    # Older ts annot files gone
    assert not any("20260420" in n for n in remaining)
    assert not any("20260421" in n for n in remaining)
