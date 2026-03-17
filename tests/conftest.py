"""Shared fixtures for Peek tests."""

import json
import pytest
from pathlib import Path


@pytest.fixture
def tmp_captures(tmp_path):
    """Create a temporary captures directory with sample data."""
    captures = tmp_path / "captures"
    captures.mkdir()
    return captures


@pytest.fixture
def sample_capture(tmp_captures):
    """Create sample capture files (JSON + PNG) in tmp dir."""
    metadata = {
        "mode": "region",
        "url": "http://localhost:3000",
        "viewport": {"width": 1280, "height": 800},
        "scroll": {"x": 0, "y": 0},
        "region": {"x": 100, "y": 200, "width": 400, "height": 300},
        "elements": [
            {
                "selector": "div.container > h1",
                "tagName": "h1",
                "classes": [],
                "id": "",
                "text": "Hello World",
                "boundingBox": {"x": 100, "y": 200, "width": 400, "height": 30},
            }
        ],
        "screenshot": "capture_latest.png",
        "timestamp": "20260316_140034",
    }
    (tmp_captures / "capture_latest.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False)
    )
    # Minimal valid PNG (1x1 pixel, red)
    png_bytes = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
        b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00"
        b"\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00"
        b"\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    (tmp_captures / "capture_latest.png").write_bytes(png_bytes)
    return tmp_captures, metadata, png_bytes


@pytest.fixture
def sample_annotated_capture(sample_capture):
    """Extend sample capture with annotation overlay."""
    captures, metadata, png_bytes = sample_capture
    metadata["mode"] = "annotate"
    metadata["annotationOverlay"] = "capture_latest_annot.png"
    (captures / "capture_latest.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False)
    )
    (captures / "capture_latest_annot.png").write_bytes(png_bytes)
    return captures, metadata, png_bytes
