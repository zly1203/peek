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
    """_check_playwright passes when Chromium exists."""
    from src.cli import _check_playwright

    # Should not raise (Chromium is installed in this env)
    _check_playwright()


def test_check_playwright_missing_binary():
    """_check_playwright exits when binary doesn't exist."""
    from src.cli import _check_playwright

    with patch("os.path.exists", return_value=False):
        with pytest.raises(SystemExit) as exc_info:
            _check_playwright()
        assert exc_info.value.code == 1
