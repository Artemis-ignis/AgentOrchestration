"""Sensitive data redaction helpers."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any


REDACTED = "[REDACTED]"

SENSITIVE_KEY = re.compile(
    r"(authorization|credential|password|secret|signature|token|api[_-]?key|"
    r"private[_-]?key)",
    re.IGNORECASE,
)
SENSITIVE_ASSIGNMENT = re.compile(
    r"(?P<key>authorization|password|secret|token|api[_-]?key)"
    r"(?P<sep>\s*[=:]\s*)"
    r"(?P<value>[^&\s,;]+)",
    re.IGNORECASE,
)
TOKEN_VALUE = re.compile(
    r"(Bearer\s+)[A-Za-z0-9._\-]+|"
    r"\b(?:sk|pk|ghp|github_pat|mch)_[A-Za-z0-9_\-]{8,}\b|"
    r"\b[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}\b",
    re.IGNORECASE,
)


def redact_text(value: str) -> str:
    """Redact common secret shapes from free-form text."""

    def replace_assignment(match: re.Match[str]) -> str:
        return f"{match.group('key')}{match.group('sep')}{REDACTED}"

    value = SENSITIVE_ASSIGNMENT.sub(replace_assignment, value)

    def replace_token(match: re.Match[str]) -> str:
        if match.group(1):
            return f"{match.group(1)}{REDACTED}"
        return REDACTED

    return TOKEN_VALUE.sub(replace_token, value)


def redact_sensitive(value: Any) -> Any:
    """Return a copy of value with sensitive keys and token strings removed."""

    if isinstance(value, Mapping):
        redacted = {}
        for key, item in value.items():
            key_text = str(key)
            redacted[key] = (
                REDACTED
                if SENSITIVE_KEY.search(key_text)
                else redact_sensitive(item)
            )
        return redacted

    if isinstance(value, tuple):
        return tuple(redact_sensitive(item) for item in value)

    if isinstance(value, Sequence) and not isinstance(
        value,
        (str, bytes, bytearray),
    ):
        return [redact_sensitive(item) for item in value]

    if isinstance(value, str):
        return redact_text(value)

    return value
