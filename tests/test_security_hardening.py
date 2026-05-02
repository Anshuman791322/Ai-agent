from __future__ import annotations

import asyncio

import httpx

from integrations.web_tools import ConstrainedWebTools
from memory.store import MemoryStore
from security.models import MemoryTag
from security.redaction import redact_secrets


def test_redact_secrets_covers_modern_token_formats():
    payload = (
        "openai=sk-proj-ABCDEFGHIJKLMNOPQRSTUVWX "
        "anthropic=sk-ant-api03-ABCDEFGHIJKLMNOPQRSTUVWX "
        "ghp=ghp_ABCDEFGHIJKLMNOPQRSTUVWX1234 "
        "gh_pat=github_pat_ABCDEFGHIJKLMNOPQRSTUVWX_1234567890 "
        "jwt=eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTYifQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c "
        "slack=xoxb-1234567890-ABCDEFGHIJKL"
    )
    cleaned = redact_secrets(payload)
    assert "sk-proj-" not in cleaned
    assert "sk-ant-" not in cleaned
    assert "ghp_" not in cleaned
    assert "github_pat_" not in cleaned
    assert "eyJhbGciOiJIUzI1NiJ9" not in cleaned
    assert "xoxb-1234567890" not in cleaned
    assert "[REDACTED_API_KEY]" in cleaned
    assert "[REDACTED_ANTHROPIC_KEY]" in cleaned
    assert "[REDACTED_GITHUB_TOKEN]" in cleaned
    assert "[REDACTED_JWT]" in cleaned
    assert "[REDACTED_SLACK_TOKEN]" in cleaned


def test_memory_store_search_does_not_leak_with_like_wildcards(tmp_path):
    store = MemoryStore(tmp_path / "memory.sqlite")
    store.remember("alpha note", MemoryTag.GENERAL)
    store.remember("bravo note", MemoryTag.GENERAL)

    assert store.search_memory("%", allowed_tags=(MemoryTag.GENERAL,)) == []
    assert store.search_memory("_", allowed_tags=(MemoryTag.GENERAL,)) == []

    direct = store.search_memory("alpha", allowed_tags=(MemoryTag.GENERAL,))
    assert len(direct) == 1
    assert "alpha" in direct[0]["content"]


def test_web_tools_block_redirect_to_private_address():
    handler_calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        handler_calls.append(str(request.url))
        if request.url.host == "example.com":
            return httpx.Response(
                302,
                text="",
                headers={"location": "http://127.0.0.1:8080/admin", "content-type": "text/html"},
            )
        return httpx.Response(200, text="", headers={"content-type": "text/html"})

    tools = ConstrainedWebTools(transport=httpx.MockTransport(handler))
    result = asyncio.run(tools.fetch("https://example.com/path"))

    assert not result.success
    assert "redirect to disallowed target blocked" in result.message
    assert all(call != "http://127.0.0.1:8080/admin" for call in handler_calls)


def test_web_tools_reject_oversize_response():
    huge = "A" * 3_000_000

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=huge, headers={"content-type": "text/html"})

    tools = ConstrainedWebTools(transport=httpx.MockTransport(handler))
    result = asyncio.run(tools.fetch("https://example.com/big"))

    assert not result.success
    assert "Page fetch failed" in result.message
