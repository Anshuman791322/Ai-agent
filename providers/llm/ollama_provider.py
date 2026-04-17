from __future__ import annotations

import logging

import httpx

from config.settings import AppSettings
from providers.llm.base import ChatMessage, ChatResult, LLMProvider, ProviderHealth


log = logging.getLogger(__name__)


class OllamaProvider(LLMProvider):
    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings
        self._client = httpx.AsyncClient(
            base_url=self.settings.ollama_base_url.rstrip("/"),
            timeout=self.settings.ollama_timeout_seconds,
        )

    async def healthcheck(self) -> ProviderHealth:
        try:
            response = await self._client.get("/api/tags")
            response.raise_for_status()
            data = response.json()
            model_names = [model.get("name", "") for model in data.get("models", [])]

            if not model_names:
                return ProviderHealth(
                    state="warn",
                    detail="Ollama is online but no local models are installed",
                )

            if not any(name == self.settings.ollama_model for name in model_names):
                return ProviderHealth(
                    state="warn",
                    detail=f"Ollama is online; missing model {self.settings.ollama_model}",
                )

            return ProviderHealth(
                state="ok",
                detail=f"online using {self.settings.ollama_model}",
            )
        except Exception as exc:
            log.debug("Ollama health check failed: %s", exc)
            return ProviderHealth(
                state="error",
                detail="offline or unreachable on 127.0.0.1:11434",
            )

    async def chat(self, messages: list[ChatMessage], system_prompt: str) -> ChatResult:
        payload_messages = [{"role": "system", "content": system_prompt}]
        payload_messages.extend({"role": msg.role, "content": msg.content} for msg in messages)

        try:
            response = await self._client.post(
                "/api/chat",
                json={
                    "model": self.settings.ollama_model,
                    "messages": payload_messages,
                    "stream": False,
                    "keep_alive": "5m",
                    "options": {
                        "temperature": 0.2,
                        "num_ctx": self.settings.ollama_num_ctx,
                        "num_predict": self.settings.ollama_num_predict,
                    },
                },
            )
            response.raise_for_status()
            data = response.json()
            content = data.get("message", {}).get("content", "").strip()
            if not content:
                raise RuntimeError("Ollama returned an empty response")
            return ChatResult(text=content, model=self.settings.ollama_model, raw=data)
        except Exception as exc:
            raise RuntimeError(
                f"Ollama request failed. Start Ollama and ensure {self.settings.ollama_model} is installed."
            ) from exc

    async def close(self) -> None:
        await self._client.aclose()
