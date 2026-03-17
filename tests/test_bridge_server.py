"""Integration tests for the Bridge Server (FastAPI endpoints)."""

import json
import base64
from unittest.mock import AsyncMock, patch
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """Create a test client with mocked Playwright."""
    # Mock Playwright lifespan so we don't launch real browser
    with patch("src.server.async_playwright") as mock_pw_cls:
        mock_pw = AsyncMock()
        mock_browser = AsyncMock()
        mock_pw.chromium.launch = AsyncMock(return_value=mock_browser)
        mock_pw_cls.return_value.start = AsyncMock(return_value=mock_pw)

        # Also mock the screenshot function
        with patch("src.server.playwright_screenshot", new_callable=AsyncMock) as mock_screenshot:
            mock_screenshot.return_value = b"fake_screenshot_png"

            from src.server import app
            with TestClient(app) as c:
                yield c, mock_screenshot


def test_setup_page(client):
    """GET / returns the setup page with bookmarklet."""
    c, _ = client
    response = c.get("/")
    assert response.status_code == 200
    assert "Peek" in response.text
    assert "bookmarklet" in response.text.lower()
    assert "Alt+R" in response.text


def test_capture_latest_no_data(client):
    """GET /api/capture/latest returns 404 when no captures exist."""
    c, _ = client
    # Clean up any existing capture files
    from src.server import CAPTURES_DIR
    json_path = CAPTURES_DIR / "capture_latest.json"
    if json_path.exists():
        json_path.unlink()

    response = c.get("/api/capture/latest")
    assert response.status_code == 404
    assert response.json()["status"] == "no captures yet"


def test_post_capture_region(client):
    """POST /api/capture saves capture data and returns ok."""
    c, mock_screenshot = client

    capture_data = {
        "mode": "region",
        "url": "http://localhost:3000",
        "viewport": {"width": 1280, "height": 800},
        "scroll": {"x": 0, "y": 0},
        "region": {"x": 100, "y": 200, "width": 400, "height": 300},
        "elements": [],
    }

    response = c.post("/api/capture", json=capture_data)
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert "timestamp" in response.json()

    # Verify screenshot was called
    mock_screenshot.assert_called_once()


def test_post_capture_saves_json(client):
    """POST /api/capture saves JSON metadata to disk."""
    c, _ = client
    from src.server import CAPTURES_DIR

    capture_data = {
        "mode": "element",
        "url": "http://localhost:3000",
        "viewport": {"width": 1280, "height": 800},
        "scroll": {"x": 0, "y": 100},
        "elements": [{"selector": "h1", "tagName": "h1", "text": "Title"}],
    }

    c.post("/api/capture", json=capture_data)

    json_path = CAPTURES_DIR / "capture_latest.json"
    assert json_path.exists()
    saved = json.loads(json_path.read_text())
    assert saved["mode"] == "element"
    assert saved["url"] == "http://localhost:3000"
    assert saved["timestamp"]


def test_post_capture_annotate_saves_overlay(client):
    """POST /api/capture in annotate mode saves annotation overlay."""
    c, _ = client
    from src.server import CAPTURES_DIR

    # Fake base64 PNG data
    fake_png = base64.b64encode(b"fake_annot_png").decode()

    capture_data = {
        "mode": "annotate",
        "url": "http://localhost:3000",
        "viewport": {"width": 1280, "height": 800},
        "scroll": {"x": 0, "y": 0},
        "annotationBounds": {"x": 50, "y": 50, "width": 200, "height": 100},
        "elements": [],
        "screenshotBase64": fake_png,
    }

    response = c.post("/api/capture", json=capture_data)
    assert response.status_code == 200

    annot_path = CAPTURES_DIR / "capture_latest_annot.png"
    assert annot_path.exists()
    assert annot_path.read_bytes() == b"fake_annot_png"


def test_capture_latest_after_post(client):
    """GET /api/capture/latest returns data after a capture is posted."""
    c, _ = client

    capture_data = {
        "mode": "region",
        "url": "http://localhost:8001",
        "viewport": {"width": 1024, "height": 768},
        "scroll": {"x": 0, "y": 0},
        "region": {"x": 0, "y": 0, "width": 500, "height": 400},
        "elements": [{"selector": "body", "tagName": "body", "text": ""}],
    }

    c.post("/api/capture", json=capture_data)

    response = c.get("/api/capture/latest")
    assert response.status_code == 200
    data = response.json()
    assert data["mode"] == "region"
    assert data["url"] == "http://localhost:8001"
