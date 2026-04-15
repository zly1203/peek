"""Server-side secret redaction for capture data.

Applied to text fields before saving capture JSON to disk so that
accidentally-visible secrets in dev pages (e.g. debug panels showing
API keys) don't leak into stored captures.
"""

import re
from typing import Any

# Patterns ordered by specificity (more specific first)
_PATTERNS = [
    # API keys (Anthropic, OpenAI, etc.)
    (re.compile(r"sk-[a-zA-Z0-9_-]{20,}"), "[REDACTED:API_KEY]"),
    # GitHub tokens
    (re.compile(r"gh[ps]_[a-zA-Z0-9]{36,}"), "[REDACTED:GITHUB_TOKEN]"),
    # AWS access keys
    (re.compile(r"AKIA[0-9A-Z]{16}"), "[REDACTED:AWS_KEY]"),
    # Bearer tokens
    (re.compile(r"Bearer\s+[a-zA-Z0-9._\-]{16,}"), "Bearer [REDACTED]"),
    # JWT tokens (header.payload.signature, base64url chars)
    (re.compile(r"eyJ[a-zA-Z0-9_\-]{10,}\.eyJ[a-zA-Z0-9_\-]{10,}\.[a-zA-Z0-9_\-]{10,}"), "[REDACTED:JWT]"),
    # Connection strings with embedded credentials
    (re.compile(r"([a-z][a-z0-9+\-.]*://)[^:/\s@]+:[^@\s/]+@"), r"\1[REDACTED]:[REDACTED]@"),
    # Generic env-style secret assignments (VAR=value where var name contains secret keywords)
    (re.compile(
        r"\b([A-Z0-9_-]*?(?:API[_-]?KEY|SECRET|TOKEN|PASSWORD|PASSWD|PRIVATE[_-]?KEY|ACCESS[_-]?KEY)[A-Z0-9_-]*)\s*[=:]\s*[\"']?([^\s\"',;]+)",
        re.IGNORECASE,
    ), r"\1=[REDACTED]"),
]

# Don't redact text shorter than this (avoids false positives on tiny strings)
_MIN_LEN = 16

# Cap text length to avoid catastrophic regex on huge inputs
_MAX_LEN = 5000


def redact_text(text: str) -> str:
    """Redact secrets from a single text string.

    - Truncates to _MAX_LEN before processing (defense against ReDoS / huge inputs)
    - Skips strings shorter than _MIN_LEN (no realistic secret fits)
    """
    if not isinstance(text, str) or len(text) < _MIN_LEN:
        return text
    if len(text) > _MAX_LEN:
        text = text[:_MAX_LEN] + "...[truncated]"
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


# Fields that get redacted recursively (case-sensitive)
_REDACT_KEYS = {
    "text", "outerHTML", "nearest_heading", "innerText", "value",
    "title", "alt", "placeholder", "label", "lastPrompt", "summary",
}


def redact_capture(data: Any) -> Any:
    """Recursively redact secrets in a capture dict/list.

    Applies to known text fields by name. Other fields pass through.
    """
    if isinstance(data, dict):
        result = {}
        for k, v in data.items():
            if k in _REDACT_KEYS and isinstance(v, str):
                result[k] = redact_text(v)
            else:
                result[k] = redact_capture(v)
        return result
    elif isinstance(data, list):
        return [redact_capture(item) for item in data]
    else:
        return data
