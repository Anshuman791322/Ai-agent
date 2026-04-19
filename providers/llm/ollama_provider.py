from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
import sys
from dataclasses import dataclass

import httpx

from config.settings import AppSettings
from providers.llm.base import ChatMessage, ChatResult, LLMProvider, ProviderHealth


log = logging.getLogger(__name__)


@dataclass(slots=True)
class ModelSelection:
    requested: str
    resolved: str | None
    state: str
    detail: str


class OllamaProvider(LLMProvider):
    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings
        self._client = httpx.AsyncClient(
            base_url=self.settings.ollama_base_url.rstrip("/"),
            timeout=self.settings.ollama_timeout_seconds,
        )
        self._warm_start_lock = asyncio.Lock()
        self._service_launch_attempted = False

    async def healthcheck(self) -> ProviderHealth:
        try:
            selection = await self._select_model()
            return ProviderHealth(state=selection.state, detail=selection.detail)
        except Exception as exc:
            log.debug("Ollama health check failed: %s", exc)
            return ProviderHealth(
                state="error",
                detail="offline or unreachable on 127.0.0.1:11434",
            )

    async def chat(self, messages: list[ChatMessage], system_prompt: str) -> ChatResult:
        payload_messages = [{"role": "system", "content": system_prompt}]
        payload_messages.extend({"role": msg.role, "content": msg.content} for msg in messages)

        selection = await self._select_model()
        if selection.resolved is None:
            raise RuntimeError(selection.detail)

        try:
            response = await self._client.post(
                "/api/chat",
                json={
                    "model": selection.resolved,
                    "messages": payload_messages,
                    "think": False,
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
            return ChatResult(text=content, model=selection.resolved, raw=data)
        except Exception as exc:
            raise RuntimeError(
                f"Ollama request failed for {selection.resolved}. Ensure the Ollama service is running and the local model is available."
            ) from exc

    async def close(self) -> None:
        await self._client.aclose()

    async def warm_start(self) -> ProviderHealth:
        async with self._warm_start_lock:
            reachable = await self._is_service_reachable()
            if not reachable and self.settings.ollama_auto_start:
                await self._try_start_service()
                reachable = await self._wait_for_service()

            if not reachable:
                return ProviderHealth(
                    state="error",
                    detail="Ollama service is offline. Install or start Ollama locally.",
                )

            selection = await self._select_model()
            if selection.resolved is None and self.settings.ollama_auto_pull:
                pulled = await self._pull_model(self.settings.ollama_model)
                if pulled:
                    selection = await self._select_model()
            if selection.resolved is None:
                return ProviderHealth(state=selection.state, detail=selection.detail)

            try:
                response = await self._client.post(
                    "/api/generate",
                    json={
                        "model": selection.resolved,
                        "prompt": "ready",
                        "think": False,
                        "stream": False,
                        "keep_alive": self.settings.ollama_keep_alive,
                        "options": {
                            "temperature": 0,
                            "num_predict": 1,
                        },
                    },
                    timeout=max(120.0, self.settings.ollama_timeout_seconds),
                )
                response.raise_for_status()
            except Exception as exc:
                return ProviderHealth(
                    state="warn",
                    detail=f"Ollama is online but model warm-up failed for {selection.resolved}: {exc}",
                )

            detail = f"model {selection.resolved} loaded and kept alive for {self.settings.ollama_keep_alive}"
            if selection.requested != selection.resolved:
                detail = f"configured model {selection.requested} missing; warmed {selection.resolved}"
            return ProviderHealth(state=selection.state, detail=detail)

    async def _select_model(self) -> ModelSelection:
        model_names = await self._fetch_model_names()
        return self._resolve_model_name(model_names)

    async def _fetch_model_names(self) -> list[str]:
        response = await self._client.get("/api/tags")
        response.raise_for_status()
        data = response.json()
        return [model.get("name", "").strip() for model in data.get("models", []) if model.get("name")]

    def _resolve_model_name(self, model_names: list[str]) -> ModelSelection:
        requested = self.settings.ollama_model

        if not model_names:
            return ModelSelection(
                requested=requested,
                resolved=None,
                state="warn",
                detail=(
                    "Ollama is online but no local models are installed. "
                    f"Run `ollama pull {requested}`."
                ),
            )

        if requested in model_names:
            return ModelSelection(
                requested=requested,
                resolved=requested,
                state="ok",
                detail=f"online using {requested}",
            )

        fallback = model_names[0]
        log.warning(
            "Configured Ollama model %s is unavailable; falling back to %s",
            requested,
            fallback,
        )
        return ModelSelection(
            requested=requested,
            resolved=fallback,
            state="warn",
            detail=f"configured model {requested} missing; using {fallback}",
        )

    async def _is_service_reachable(self) -> bool:
        try:
            response = await self._client.get("/api/tags")
            response.raise_for_status()
            return True
        except Exception:
            return False

    async def _wait_for_service(self) -> bool:
        deadline = asyncio.get_running_loop().time() + max(1.0, self.settings.ollama_start_timeout_seconds)
        while asyncio.get_running_loop().time() < deadline:
            if await self._is_service_reachable():
                return True
            await asyncio.sleep(0.5)
        return await self._is_service_reachable()

    async def _try_start_service(self) -> None:
        if self._service_launch_attempted:
            return
        self._service_launch_attempted = True

        ollama_exe = self._ollama_cli_path()
        if not ollama_exe:
            log.warning("Ollama CLI not found while attempting auto-start")
            return

        log.info("Attempting to auto-start Ollama service using %s", ollama_exe)
        creationflags = 0
        if sys.platform.startswith("win"):
            creationflags = (
                getattr(subprocess, "DETACHED_PROCESS", 0)
                | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                | getattr(subprocess, "CREATE_NO_WINDOW", 0)
            )

        try:
            subprocess.Popen(
                [ollama_exe, "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creationflags,
            )
        except Exception:
            log.exception("Failed to auto-start Ollama service")

    async def _pull_model(self, model_name: str) -> bool:
        ollama_exe = self._ollama_cli_path()
        if not ollama_exe:
            log.warning("Ollama CLI not found while attempting to pull %s", model_name)
            return False

        log.info("Pulling Ollama model %s", model_name)
        creationflags = 0
        if sys.platform.startswith("win"):
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        try:
            process = await asyncio.create_subprocess_exec(
                ollama_exe,
                "pull",
                model_name,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
                creationflags=creationflags,
            )
            _, stderr = await process.communicate()
        except Exception:
            log.exception("Failed to pull Ollama model %s", model_name)
            return False

        if process.returncode != 0:
            error = stderr.decode(errors="ignore").strip()
            log.warning("Ollama pull failed for %s: %s", model_name, error or process.returncode)
            return False
        return True

    @staticmethod
    def _ollama_cli_path() -> str | None:
        return shutil.which("ollama") or shutil.which("ollama.exe")
