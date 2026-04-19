from __future__ import annotations

import re


_SECRET_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
            re.IGNORECASE | re.DOTALL,
        ),
        "[REDACTED_PRIVATE_KEY]",
    ),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"), "[REDACTED_GITHUB_TOKEN]"),
    (re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"), "[REDACTED_API_KEY]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[REDACTED_AWS_ACCESS_KEY]"),
    (
        re.compile(r"(?i)\b(?:api[_ -]?key|token|secret|password|passwd|sessionid)\b\s*[:=]\s*[^\s\"';]+"),
        "[REDACTED_SECRET_ASSIGNMENT]",
    ),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._-]{12,}\b"), "Bearer [REDACTED]"),
)


def redact_secrets(text: str) -> str:
    cleaned = text
    for pattern, replacement in _SECRET_PATTERNS:
        cleaned = pattern.sub(replacement, cleaned)
    return cleaned


def sanitize_for_log(text: str, max_chars: int = 240) -> str:
    cleaned = redact_secrets(text)
    cleaned = " ".join(cleaned.strip().split())
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max_chars - 3].rstrip() + "..."


def sanitize_untrusted_text(text: str, max_chars: int) -> str:
    cleaned = redact_secrets(text.replace("\x00", " "))
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max_chars - 16].rstrip() + "\n[TRUNCATED]"


def looks_sensitive(text: str) -> bool:
    redacted = redact_secrets(text)
    if redacted != text:
        return True
    lowered = text.lower()
    keywords = ("token", "secret", "password", "cookie", "session", "key")
    return any(keyword in lowered for keyword in keywords)

