from __future__ import annotations

import logging
import os
import time
from typing import Any

import httpx

from config.settings import AppSettings
from integrations.secret_store import GeminiKeyStore
from providers.llm.base import ChatMessage, ChatResult, LLMProvider, ProviderHealth


log = logging.getLogger(__name__)


class GeminiProvider(LLMProvider):
    provider_name = "Gemini Flash"
    requires_network = True

    def __init__(
        self,
        settings: AppSettings,
        client: httpx.AsyncClient | None = None,
        key_store: GeminiKeyStore | None = None,
    ) -> None:
        self.settings = settings
        self.key_store = key_store
        self._client = client or httpx.AsyncClient(
            base_url=self.settings.gemini_api_base_url.rstrip("/"),
            timeout=self.settings.gemini_timeout_seconds,
        )
        self._owns_client = client is None
        self._last_health: ProviderHealth | None = None
        self._last_health_at = 0.0

    async def healthcheck(self) -> ProviderHealth:
        key = self._api_key()
        if not key:
            return ProviderHealth(
                state="warn",
                detail=f"Gemini API key missing; set {self.settings.gemini_api_key_env} or GEMINI_API_KEY",
            )

        now = time.monotonic()
        if self._last_health is not None and now - self._last_health_at < 60:
            return self._last_health

        try:
            response = await self._client.get(
                f"/models/{self.settings.gemini_model}",
                headers=self._headers(key),
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            detail = "Gemini key or model was rejected" if status in {400, 401, 403, 404} else "Gemini health check failed"
            health = ProviderHealth(state="error", detail=f"{detail} ({status})")
        except httpx.HTTPError as exc:
            log.debug("Gemini health check failed: %s", exc)
            health = ProviderHealth(state="error", detail="Gemini API is unreachable")
        else:
            health = ProviderHealth(state="ok", detail=f"online using {self.settings.gemini_model}")

        self._last_health = health
        self._last_health_at = now
        return health

    async def chat(self, messages: list[ChatMessage], system_prompt: str) -> ChatResult:
        key = self._api_key()
        if not key:
            raise RuntimeError(f"Gemini API key missing; set {self.settings.gemini_api_key_env} or GEMINI_API_KEY")

        payload = {
            "system_instruction": {"parts": [{"text": system_prompt}]},
            "contents": self._contents(messages),
            "generationConfig": self._generation_config(),
        }
        try:
            response = await self._client.post(
                f"/models/{self.settings.gemini_model}:generateContent",
                headers=self._headers(key),
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            raise RuntimeError(f"Gemini request failed with HTTP {status}") from exc
        except Exception as exc:
            raise RuntimeError("Gemini request failed") from exc

        text = self._extract_text(data)
        if not text:
            raise RuntimeError("Gemini returned an empty response")
        return ChatResult(text=text, model=self.settings.gemini_model, raw=self._safe_raw(data))

    async def warm_start(self) -> ProviderHealth:
        return await self.healthcheck()

    def invalidate_health_cache(self) -> None:
        self._last_health = None
        self._last_health_at = 0.0

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def _api_key(self) -> str:
        if self.key_store is not None:
            stored = self.key_store.get_key()
            if stored:
                return stored
        primary = os.getenv(self.settings.gemini_api_key_env, "").strip()
        if primary:
            return primary
        if self.settings.gemini_api_key_env != "GEMINI_API_KEY":
            return os.getenv("GEMINI_API_KEY", "").strip()
        return ""

    @staticmethod
    def _headers(api_key: str) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        }

    def _contents(self, messages: list[ChatMessage]) -> list[dict[str, Any]]:
        contents: list[dict[str, Any]] = []
        for message in messages:
            role = "model" if message.role == "assistant" else "user"
            contents.append({"role": role, "parts": [{"text": message.content}]})
        if not contents:
            contents.append({"role": "user", "parts": [{"text": ""}]})
        return contents

    def _generation_config(self) -> dict[str, Any]:
        config: dict[str, Any] = {
            "temperature": self.settings.gemini_temperature,
            "maxOutputTokens": self.settings.gemini_max_output_tokens,
        }
        if self.settings.gemini_disable_thinking:
            config["thinkingConfig"] = {"thinkingBudget": 0}
        return config

    @staticmethod
    def _extract_text(data: dict[str, Any]) -> str:
        candidates = data.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            return ""
        content = candidates[0].get("content", {}) if isinstance(candidates[0], dict) else {}
        parts = content.get("parts", []) if isinstance(content, dict) else []
        texts = [part.get("text", "") for part in parts if isinstance(part, dict)]
        return "\n".join(text for text in texts if text).strip()

    @staticmethod
    def _safe_raw(data: dict[str, Any]) -> dict[str, Any]:
        return {
            "modelVersion": data.get("modelVersion", ""),
            "usageMetadata": data.get("usageMetadata", {}),
        }
