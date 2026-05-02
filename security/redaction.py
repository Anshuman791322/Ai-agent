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
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"), "[REDACTED_GITHUB_TOKEN]"),
    (re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b"), "[REDACTED_ANTHROPIC_KEY]"),
    (re.compile(r"\bsk-(?:proj-|svcacct-|admin-)?[A-Za-z0-9_-]{20,}\b"), "[REDACTED_API_KEY]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[REDACTED_AWS_ACCESS_KEY]"),
    (re.compile(r"\baws_secret_access_key\s*[:=]\s*['\"]?[A-Za-z0-9/+=]{40}['\"]?", re.IGNORECASE), "[REDACTED_AWS_SECRET_KEY]"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"), "[REDACTED_JWT]"),
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"), "[REDACTED_SLACK_TOKEN]"),
    (
        re.compile(r"(?i)\b(?:api[_ -]?key|token|secret|password|passwd|sessionid)\b\s*[:=]\s*[^\s\"';]{4,128}"),
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
    patterns = (
        r"(?i)\b(?:token|secret|password|passwd|cookie|session(?:id)?)\b\s*(?:is|=|:)\s*\S+",
        r"(?i)\b(?:api|access|private|secret|ssh)\s*[_ -]?\s*key\b\s*(?:is|=|:)\s*\S+",
        r"(?i)-----BEGIN [A-Z ]*PRIVATE KEY-----",
    )
    return any(re.search(pattern, text) for pattern in patterns)
