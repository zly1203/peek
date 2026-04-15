"""Unit tests for server-side secret redaction."""

from src.redact import redact_text, redact_capture


# ─── redact_text ───

def test_redacts_anthropic_api_key():
    text = "Welcome to dashboard, key=sk-ant-api03-AbC123XyZ_ohyeahabunchmore"
    out = redact_text(text)
    assert "sk-ant-api03" not in out
    assert "[REDACTED:API_KEY]" in out


def test_redacts_openai_api_key():
    text = "Your token: sk-proj-abc123def456ghi789jkl"
    out = redact_text(text)
    assert "sk-proj-abc123" not in out


def test_redacts_github_token():
    text = "Auth: ghp_abcdefghijklmnopqrstuvwxyz1234567890ABC"
    out = redact_text(text)
    assert "ghp_abcdefghij" not in out
    assert "[REDACTED:GITHUB_TOKEN]" in out


def test_redacts_aws_access_key():
    text = "Found AWS key AKIAIOSFODNN7EXAMPLE in env"
    out = redact_text(text)
    assert "AKIAIOSFODNN7EXAMPLE" not in out
    assert "[REDACTED:AWS_KEY]" in out


def test_redacts_bearer_token():
    text = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
    out = redact_text(text)
    assert "eyJhbGci" not in out
    assert "Bearer [REDACTED]" in out


def test_redacts_jwt():
    text = "JWT: eyJhbGciOiJIUzI1NiIs.eyJzdWIiOiIxMjM0NTY3ODkw.SflKxwRJSMeKKF2QT4"
    out = redact_text(text)
    assert "[REDACTED:JWT]" in out


def test_redacts_connection_string_credentials():
    text = "DB: postgres://admin:supersecret@db.local:5432/myapp"
    out = redact_text(text)
    assert "supersecret" not in out
    assert "admin" not in out
    assert "[REDACTED]" in out
    assert "db.local:5432" in out  # host should remain


def test_redacts_env_style_assignments():
    cases = [
        "API_KEY=secret_value_here_long_enough",
        "DATABASE_PASSWORD: my_secret_pwd_12345",
        "JWT_SECRET=supersecretjwt9876",
        "ACCESS_TOKEN: ya29.abc123def456",
    ]
    for text in cases:
        out = redact_text(text)
        assert "[REDACTED]" in out, f"failed to redact: {text}"


def test_does_not_redact_innocent_text():
    """Common UI text should pass through unchanged."""
    cases = [
        "Welcome back, user!",
        "Click here to subscribe",
        "Total: $123.45",
        "Last login: 2026-04-01",
    ]
    for text in cases:
        assert redact_text(text) == text


def test_short_text_passes_through():
    """Strings shorter than threshold are not processed."""
    assert redact_text("hi") == "hi"
    assert redact_text("sk-test") == "sk-test"  # too short to be a real key


def test_truncates_huge_input():
    """Defends against ReDoS / huge input."""
    huge = "a" * 100000
    out = redact_text(huge)
    assert len(out) < 6000  # max + truncation marker
    assert "[truncated]" in out


def test_non_string_passthrough():
    assert redact_text(None) is None
    assert redact_text(42) == 42
    assert redact_text(["list"]) == ["list"]


# ─── redact_capture (recursive) ───

def test_redacts_nested_dom_context_heading():
    data = {
        "mode": "element",
        "elements": [{
            "tagName": "button",
            "text": "Click me",
            "domContext": {
                "nearest_heading": "h2: Reset password for sk-ant-api03-realsecretkey12345abc",
                "ancestor_chain": ["body", "main"],
                "child_count": 0,
            }
        }]
    }
    out = redact_capture(data)
    heading = out["elements"][0]["domContext"]["nearest_heading"]
    assert "sk-ant-api03" not in heading
    assert "[REDACTED:API_KEY]" in heading


def test_redacts_element_text():
    data = {
        "elements": [{
            "text": "Your API_KEY=mysuperSecret_key_value123",
        }]
    }
    out = redact_capture(data)
    assert "[REDACTED]" in out["elements"][0]["text"]


def test_redacts_outerHTML():
    data = {
        "elements": [{
            "outerHTML": '<div>Token: ghp_realgithubtoken1234567890abcdefghij1234567890</div>',
        }]
    }
    out = redact_capture(data)
    assert "ghp_realgithubtoken" not in out["elements"][0]["outerHTML"]


def test_does_not_redact_non_text_fields():
    """Selector, classes, tagName etc. should not be touched."""
    data = {
        "elements": [{
            "selector": "button.primary",
            "tagName": "button",
            "classes": ["primary", "btn"],
            "boundingBox": {"x": 10, "y": 20, "width": 100, "height": 40},
        }]
    }
    out = redact_capture(data)
    assert out == data  # unchanged


def test_handles_empty_and_missing_fields():
    """Should not crash on weird input."""
    assert redact_capture({}) == {}
    assert redact_capture([]) == []
    assert redact_capture({"text": ""}) == {"text": ""}
    assert redact_capture({"text": None}) == {"text": None}


def test_does_not_modify_input():
    """Should not mutate input dict."""
    data = {"elements": [{"text": "API_KEY=secret_value_long_enough"}]}
    original = {"elements": [{"text": "API_KEY=secret_value_long_enough"}]}
    redact_capture(data)
    assert data == original
