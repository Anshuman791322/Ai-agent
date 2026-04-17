from __future__ import annotations

import asyncio
import logging
import threading

from actions.system_actions import SystemActions
from config.settings import AppSettings
from core.app_state import AppState
from core.event_bus import EventBus
from memory.store import MemoryStore
from providers.llm.base import ChatMessage
from providers.llm.ollama_provider import OllamaProvider
from voice.stt_whisper import WhisperSTT


log = logging.getLogger(__name__)


class Orchestrator:
    def __init__(
        self,
        settings: AppSettings,
        state: AppState,
        bus: EventBus,
        memory: MemoryStore,
        llm: OllamaProvider,
        voice: WhisperSTT,
        actions: SystemActions,
    ) -> None:
        self.settings = settings
        self.state = state
        self.bus = bus
        self.memory = memory
        self.llm = llm
        self.voice = voice
        self.actions = actions

        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="jarvis-orchestrator")
        self._running = False

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread.start()
        self._publish_log("system", "Boot sequence complete. Local-first subsystems are coming online.")
        self.refresh_health()

    def shutdown(self) -> None:
        if not self._running:
            return

        future = asyncio.run_coroutine_threadsafe(self._shutdown_async(), self._loop)
        try:
            future.result(timeout=5)
        except Exception:
            pass

        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=2)
        self._running = False

    def submit_text(self, text: str) -> None:
        cleaned = text.strip()
        if not cleaned or not self._running:
            return
        asyncio.run_coroutine_threadsafe(self._handle_text(cleaned, source="typed"), self._loop)

    def submit_voice_capture(self) -> None:
        if not self._running:
            return
        asyncio.run_coroutine_threadsafe(self._capture_voice_input(), self._loop)

    def refresh_health(self) -> None:
        if not self._running:
            return
        asyncio.run_coroutine_threadsafe(self._refresh_health(), self._loop)

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    async def _shutdown_async(self) -> None:
        await self.llm.close()

    async def _capture_voice_input(self) -> None:
        self.state.set_status("voice", "busy", f"recording {self.settings.voice_record_seconds}s clip")
        self._publish_status()
        self._publish_log("system", f"Recording voice input for {self.settings.voice_record_seconds} seconds.")

        try:
            transcript = await self.voice.transcribe_once()
        except Exception as exc:
            self.state.set_status("voice", "error", str(exc))
            self._publish_status()
            self._publish_log("system", f"Voice capture failed: {exc}")
            return

        if not transcript:
            self.state.set_status("voice", "warn", "no speech detected")
            self._publish_status()
            self._publish_log("system", "No speech was detected in the recorded clip.")
            return

        self.state.set_status("voice", "ok", "transcription complete")
        self._publish_status()
        await self._handle_text(transcript, source="voice")

    async def _handle_text(self, text: str, source: str) -> None:
        prefix = "[voice] " if source == "voice" else ""
        self.memory.append_message("user", text, source)
        self._publish_log("user", f"{prefix}{text}")

        try:
            response = await self._dispatch(text)
        except Exception as exc:
            log.exception("Request handling failed")
            response = f"Subsystem error: {exc}"

        self.memory.append_message("assistant", response, "assistant")
        self._publish_log("assistant", response)

    async def _dispatch(self, text: str) -> str:
        if text.startswith("/"):
            return await self._handle_local_command(text)
        return await self._generate_llm_response(text)

    async def _handle_local_command(self, text: str) -> str:
        command, _, args = text.partition(" ")
        args = args.strip()

        if command == "/help":
            return (
                "Commands: /help, /open <url-or-path>, /ps <safe PowerShell>, "
                "/remember <note>, /health."
            )

        if command == "/open":
            result = await self.actions.open_target(args)
            return result.message

        if command == "/ps":
            result = await self.actions.run_powershell_safe(args)
            if result.output:
                return f"{result.message}\n{result.output}"
            return result.message

        if command == "/remember":
            if not args:
                return "Nothing to store."
            self.memory.remember(args)
            return "Stored in local memory."

        if command == "/health":
            await self._refresh_health()
            statuses = self.state.snapshot_statuses()
            return " | ".join(
                f"{name.upper()}={payload['state']} ({payload['detail']})"
                for name, payload in statuses.items()
            )

        return "Unknown command. Use /help for the local command set."

    async def _generate_llm_response(self, text: str) -> str:
        relevant_memory = self.memory.search_memory(text, limit=3)
        system_prompt = self.settings.system_prompt
        if relevant_memory:
            system_prompt += "\nUseful local memory:\n" + "\n".join(f"- {item}" for item in relevant_memory)

        history = [
            ChatMessage(role=item["role"], content=item["content"])
            for item in self.memory.recent_messages(limit=self.settings.memory_history_limit)
        ]

        self.state.set_status("llm", "busy", f"querying {self.settings.ollama_model}")
        self._publish_status()

        try:
            result = await self.llm.chat(history, system_prompt)
            self.state.set_status("llm", "ok", f"responded with {result.model}")
            self._publish_status()
            return result.text.strip()
        except Exception as exc:
            self.state.set_status("llm", "error", str(exc))
            self._publish_status()
            return (
                "Ollama is unavailable. Start Ollama and make sure "
                f"{self.settings.ollama_model} is installed. Local commands still work."
            )

    async def _refresh_health(self) -> None:
        llm_health = await self.llm.healthcheck()
        voice_health = await self.voice.healthcheck()
        memory_health = self.memory.healthcheck()
        action_health = self.actions.healthcheck()

        self.state.set_status("llm", llm_health.state, llm_health.detail)
        self.state.set_status("voice", voice_health["state"], voice_health["detail"])
        self.state.set_status("memory", memory_health["state"], memory_health["detail"])
        self.state.set_status("actions", action_health["state"], action_health["detail"])
        self._publish_status()

    def _publish_log(self, role: str, text: str) -> None:
        payload = self.state.add_log(role, text).to_dict()
        self.bus.publish("log", payload)

    def _publish_status(self) -> None:
        self.bus.publish("status", self.state.snapshot_statuses())
