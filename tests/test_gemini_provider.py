from __future__ import annotations

import asyncio

from config.settings import AppSettings
from integrations.secret_store import GeminiKeyStore
from providers.llm.base import ChatMessage
from providers.llm.gemini_provider import GeminiProvider


class _FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> dict:
        return self._payload


class _FakeClient:
    def __init__(self, expected_key: str = "test-key") -> None:
        self.expected_key = expected_key
        self.gets: list[dict] = []
        self.posts: list[dict] = []
        self.closed = False

    async def get(self, path: str, headers: dict[str, str]):
        assert path == "/models/gemini-2.5-flash"
        self.gets.append({"path": path, "headers": headers})
        assert headers["x-goog-api-key"] == self.expected_key
        return _FakeResponse({"name": "models/gemini-2.5-flash"})

    async def post(self, path: str, headers: dict[str, str], json: dict):
        self.posts.append({"path": path, "headers": headers, "json": json})
        return _FakeResponse(
            {
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {"text": "Gemini response"},
                            ]
                        }
                    }
                ],
                "usageMetadata": {"totalTokenCount": 12},
            }
        )

    async def aclose(self) -> None:
        self.closed = True


class _FakeSecretBackend:
    def __init__(self, value: str = "", available: bool = True) -> None:
        self.value = value
        self.is_available = available
        self.writes: list[tuple[str, str]] = []
        self.deleted: list[str] = []

    def available(self) -> bool:
        return self.is_available

    def read(self, target_name: str) -> str:
        del target_name
        return self.value

    def write(self, target_name: str, value: str) -> None:
        self.writes.append((target_name, value))
        self.value = value

    def delete(self, target_name: str) -> None:
        self.deleted.append(target_name)
        self.value = ""


def test_gemini_provider_uses_env_key_and_generate_content(monkeypatch):
    settings = AppSettings()
    client = _FakeClient()
    provider = GeminiProvider(settings, client=client)
    monkeypatch.setenv("JARVIS_GEMINI_API_KEY", "test-key")

    async def run_case():
        health = await provider.healthcheck()
        result = await provider.chat([ChatMessage(role="user", content="hello")], "system prompt")
        return health, result

    health, result = asyncio.run(run_case())

    assert health.state == "ok"
    assert result.text == "Gemini response"
    assert result.model == "gemini-2.5-flash"
    assert client.posts[0]["path"] == "/models/gemini-2.5-flash:generateContent"
    assert client.posts[0]["headers"]["x-goog-api-key"] == "test-key"
    assert client.posts[0]["json"]["system_instruction"]["parts"][0]["text"] == "system prompt"
    assert client.posts[0]["json"]["generationConfig"]["thinkingConfig"]["thinkingBudget"] == 0


def test_gemini_provider_degrades_without_key(monkeypatch):
    settings = AppSettings()
    provider = GeminiProvider(settings, client=_FakeClient())
    monkeypatch.delenv("JARVIS_GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    health = asyncio.run(provider.healthcheck())

    assert health.state == "warn"
    assert "JARVIS_GEMINI_API_KEY" in health.detail


def test_gemini_provider_accepts_standard_env_key(monkeypatch):
    settings = AppSettings()
    client = _FakeClient(expected_key="standard-test-key")
    provider = GeminiProvider(settings, client=client)
    monkeypatch.delenv("JARVIS_GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "standard-test-key")

    health = asyncio.run(provider.healthcheck())

    assert health.state == "ok"
    assert client.gets[0]["headers"]["x-goog-api-key"] == "standard-test-key"


def test_gemini_provider_prefers_credential_manager_key(monkeypatch):
    settings = AppSettings()
    key_store = GeminiKeyStore(settings, backend=_FakeSecretBackend("stored-test-key"))
    client = _FakeClient(expected_key="stored-test-key")
    provider = GeminiProvider(settings, client=client, key_store=key_store)
    monkeypatch.setenv("JARVIS_GEMINI_API_KEY", "env-test-key")

    health = asyncio.run(provider.healthcheck())

    assert health.state == "ok"
    assert client.gets[0]["headers"]["x-goog-api-key"] == "stored-test-key"


def test_gemini_key_store_saves_and_clears_without_exposing_key():
    settings = AppSettings()
    backend = _FakeSecretBackend()
    key_store = GeminiKeyStore(settings, backend=backend)

    key_store.set_key("stored-test-key")
    state = key_store.state()
    key_store.clear_key()

    assert key_store.get_key() == ""
    assert state.has_key is True
    assert state.source == "Windows Credential Manager"
    assert backend.writes[0][1] == "stored-test-key"
    assert backend.deleted == [key_store.target_name]
