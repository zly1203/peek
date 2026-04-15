"""Unit tests for CLI entry point."""

import sys
import pytest
from unittest.mock import patch, MagicMock


def test_cli_help(capsys):
    """CLI --help shows peek with serve and mcp commands."""
    with patch("sys.argv", ["peek", "--help"]):
        with pytest.raises(SystemExit) as exc_info:
            from src.cli import main
            main()
        assert exc_info.value.code == 0

    captured = capsys.readouterr()
    assert "peek" in captured.out
    assert "serve" in captured.out
    assert "mcp" in captured.out


def test_cli_serve_help(capsys):
    """serve --help shows port and host options."""
    with patch("sys.argv", ["peek", "serve", "--help"]):
        with pytest.raises(SystemExit) as exc_info:
            from src.cli import main
            main()
        assert exc_info.value.code == 0

    captured = capsys.readouterr()
    assert "--port" in captured.out
    assert "--host" in captured.out


def test_cli_mcp_help(capsys):
    """mcp --help shows port and host options."""
    with patch("sys.argv", ["peek", "mcp", "--help"]):
        with pytest.raises(SystemExit) as exc_info:
            from src.cli import main
            main()
        assert exc_info.value.code == 0

    captured = capsys.readouterr()
    assert "--port" in captured.out
    assert "--host" in captured.out


def test_check_playwright_success():
    """_check_playwright returns True when Chromium exists."""
    from src.cli import _check_playwright

    # Chromium is installed in this env
    assert _check_playwright() is True


def test_check_playwright_missing_binary():
    """_check_playwright returns False when binary doesn't exist."""
    from src.cli import _check_playwright

    with patch("os.path.exists", return_value=False):
        assert _check_playwright() is False


def test_ensure_playwright_exits_when_missing():
    """_ensure_playwright exits with helpful message when Chromium missing."""
    from src.cli import _ensure_playwright

    with patch("src.cli._check_playwright", return_value=False):
        with pytest.raises(SystemExit) as exc_info:
            _ensure_playwright()
        assert exc_info.value.code == 1


def test_cli_setup_help(capsys):
    """setup command shows up in help."""
    with patch("sys.argv", ["peek", "--help"]):
        with pytest.raises(SystemExit):
            from src.cli import main
            main()
    captured = capsys.readouterr()
    assert "setup" in captured.out
