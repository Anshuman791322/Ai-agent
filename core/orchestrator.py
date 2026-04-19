from __future__ import annotations

import asyncio
import logging
import re
import threading

from actions.system_actions import SystemActions
from config.settings import AppSettings
from core.app_state import AppState
from core.event_bus import EventBus
from integrations.windows_context import WindowContext, WindowsContextProbe
from memory.store import MemoryStore
from providers.llm.base import ChatMessage
from providers.llm.ollama_provider import OllamaProvider
from voice.wake_listener import WakePhraseListener
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
        context_probe: WindowsContextProbe | None = None,
    ) -> None:
        self.settings = settings
        self.state = state
        self.bus = bus
        self.memory = memory
        self.llm = llm
        self.voice = voice
        self.actions = actions
        self.context_probe = context_probe

        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="jarvis-orchestrator")
        self._running = False
        self._voice_listener: WakePhraseListener | None = None
        self._voice_runtime_lock = threading.Lock()
        self._voice_runtime_state = "unknown"
        self._voice_runtime_detail = "waiting for startup"
        self._desktop_context_lock = threading.Lock()
        self._desktop_context = WindowContext()

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread.start()
        self._publish_log("system", "Boot sequence complete. Local-first subsystems are coming online.")
        self._start_voice_activation()
        if self.settings.desktop_context_enabled:
            self.refresh_context()
        if self.settings.whisper_preload_on_startup:
            asyncio.run_coroutine_threadsafe(self._warm_start_voice_stack(), self._loop)
        asyncio.run_coroutine_threadsafe(self._warm_start_local_model(), self._loop)
        self.refresh_health()

    def shutdown(self) -> None:
        if self._voice_listener is not None:
            self._voice_listener.stop()
            self._voice_listener = None

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

    def submit_voice_transcript(self, text: str, raw_transcript: str | None = None) -> None:
        cleaned = self._normalize_user_text(text)
        if not cleaned or not self._running:
            return

        if raw_transcript and raw_transcript.strip():
            self._publish_log("system", f"Wake phrase transcript: {raw_transcript.strip()}")

        asyncio.run_coroutine_threadsafe(self._handle_text(cleaned, source="voice"), self._loop)

    def refresh_health(self) -> None:
        if not self._running:
            return
        asyncio.run_coroutine_threadsafe(self._refresh_health(), self._loop)

    def refresh_context(self) -> None:
        if not self._running or not self.settings.desktop_context_enabled or self.context_probe is None:
            return
        asyncio.run_coroutine_threadsafe(self._refresh_desktop_context(), self._loop)

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

        transcript = self._normalize_user_text(transcript) or transcript
        self.state.set_status("voice", "ok", "transcription complete")
        self._publish_status()
        await self._handle_text(transcript, source="voice")

    async def _handle_text(self, text: str, source: str) -> None:
        prefix = "[voice] " if source == "voice" else ""
        await asyncio.to_thread(self.memory.append_message, "user", text, source)
        self._publish_log("user", f"{prefix}{text}")

        try:
            response = await self._dispatch(text)
        except Exception as exc:
            log.exception("Request handling failed")
            response = f"Subsystem error: {exc}"

        await asyncio.to_thread(self.memory.append_message, "assistant", response, "assistant")
        self._publish_log("assistant", response)

    async def _dispatch(self, text: str) -> str:
        if text.startswith("/"):
            return await self._handle_local_command(text)
        fast_response = await self._handle_natural_command(text)
        if fast_response is not None:
            return fast_response
        return await self._generate_llm_response(text)

    async def _handle_local_command(self, text: str) -> str:
        command, _, args = text.partition(" ")
        args = args.strip()

        if command == "/help":
            return (
                "Commands: /help, /open <url-or-path>, /ps <safe PowerShell>, "
                "/remember <note>, /health. Natural commands also work, for example "
                "'open claude code' or 'open file explorer'."
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
        desktop_context = self._desktop_context_text()
        if desktop_context:
            system_prompt += f"\nActive Windows desktop context: {desktop_context}"
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

    async def _handle_natural_command(self, text: str) -> str | None:
        normalized = text.lower().strip()

        claude_task = self._extract_claude_task(text)
        if claude_task:
            result = await self.actions.run_claude_code_task(claude_task)
            return result.message

        browser_intent = self._extract_browser_intent(text)
        if browser_intent is not None:
            target, browser = browser_intent
            result = await self.actions.open_in_browser(target, browser)
            return result.message

        open_match = re.match(r"^(?:please\s+)?(?:open|launch|start|run)\s+(?P<target>.+)$", text, flags=re.IGNORECASE)
        if open_match:
            target = self._normalize_user_text(open_match.group("target"))
            canonical = self.actions.canonicalize_launch_target(target)
            if canonical is not None:
                result = await self.actions.launch_named_app(target)
                return result.message
            if self._looks_like_open_target(target):
                result = await self.actions.open_target(target)
                return result.message
            resolved_site = self.actions.resolve_site_target(target)
            if resolved_site is not None:
                result = await self.actions.open_in_browser(resolved_site, "chrome")
                return result.message

        direct_launch = self.actions.canonicalize_launch_target(text)
        if direct_launch is not None and len(normalized.split()) <= 4:
            result = await self.actions.launch_named_app(direct_launch)
            return result.message

        if normalized in {"health check", "system health", "show health", "status check"}:
            return await self._handle_local_command("/health")

        if normalized in {
            "what app is active",
            "what app is open",
            "what window is active",
            "where am i",
            "what am i looking at",
        }:
            context = self._desktop_context_text()
            return context or "No active desktop context is available."

        if normalized.startswith("remember "):
            remembered = text.split(" ", 1)[1].strip()
            if remembered:
                self.memory.remember(remembered)
                return "Stored in local memory."

        return None

    async def _refresh_health(self) -> None:
        llm_health = await self.llm.healthcheck()
        voice_health = await self.voice.healthcheck()
        memory_health = self.memory.healthcheck()
        action_health = self.actions.healthcheck()

        with self._voice_runtime_lock:
            runtime_state = self._voice_runtime_state
            runtime_detail = self._voice_runtime_detail

        self.state.set_status("llm", llm_health.state, llm_health.detail)
        voice_state = voice_health["state"]
        voice_detail = voice_health["detail"]
        if self.settings.voice_activation_enabled:
            if voice_state == "ok":
                if runtime_state in {"ok", "busy", "warn", "error"}:
                    voice_state = runtime_state
                voice_detail = f"{voice_detail}; {runtime_detail}"
            elif runtime_state in {"warn", "error"}:
                voice_detail = f"{voice_detail}; {runtime_detail}"
        self.state.set_status("voice", voice_state, voice_detail)
        self.state.set_status("memory", memory_health["state"], memory_health["detail"])
        self.state.set_status("actions", action_health["state"], action_health["detail"])
        self._publish_status()

    async def _refresh_desktop_context(self) -> None:
        if self.context_probe is None or not self.context_probe.available():
            return

        try:
            snapshot = await asyncio.to_thread(self.context_probe.snapshot)
        except Exception as exc:
            log.debug("Desktop context refresh failed: %s", exc)
            return

        publish = False
        with self._desktop_context_lock:
            if snapshot != self._desktop_context:
                self._desktop_context = snapshot
                publish = True

        if publish:
            self.bus.publish("context", snapshot.to_dict())

    def _publish_log(self, role: str, text: str) -> None:
        payload = self.state.add_log(role, text).to_dict()
        self.bus.publish("log", payload)

    def _publish_status(self) -> None:
        self.bus.publish("status", self.state.snapshot_statuses())

    async def _warm_start_local_model(self) -> None:
        self.state.set_status("llm", "busy", f"warming {self.settings.ollama_model}")
        self._publish_status()
        self._publish_log("system", f"Starting local model runtime for {self.settings.ollama_model}.")

        try:
            health = await self.llm.warm_start()
        except Exception as exc:
            log.exception("Local model warm-start failed")
            self.state.set_status("llm", "error", str(exc))
            self._publish_status()
            self._publish_log("system", f"Local model warm-start failed: {exc}")
            return

        self.state.set_status("llm", health.state, health.detail)
        self._publish_status()
        self._publish_log("system", f"LLM startup: {health.detail}")

    async def _warm_start_voice_stack(self) -> None:
        self._publish_log("system", f"Preloading local voice model {self.settings.whisper_model_size}.")
        try:
            detail = await self.voice.warm_start()
        except Exception as exc:
            log.exception("Voice model preload failed")
            self._publish_log("system", f"Voice model preload failed: {exc}")
            return

        self._publish_log("system", f"Voice startup: {detail}")
        await self._refresh_health()

    def _start_voice_activation(self) -> None:
        if not self.settings.voice_activation_enabled:
            self._set_voice_runtime("warn", "wake listening disabled")
            return

        try:
            self._voice_listener = WakePhraseListener(
                self.settings,
                self.voice,
                on_command=self._handle_wake_command,
                on_status=self._set_voice_runtime,
            )
            self._voice_listener.start()
            log.info("Voice activation enabled with wake phrase '%s'", self.settings.voice_wake_phrase)
            if self.settings.voice_activation_engine == "transcript":
                activation_message = (
                    f"Voice activation online in transcript wake mode. Say '{self.settings.voice_wake_phrase}' to arm the next command."
                )
            else:
                activation_message = (
                    f"Voice activation online. Say '{self.settings.voice_wake_phrase}' followed by your command."
                )
            self._publish_log(
                "system",
                activation_message,
            )
        except Exception as exc:
            log.exception("Voice activation failed to start")
            self._set_voice_runtime("error", f"voice activation unavailable: {exc}")
            self._publish_log("system", f"Voice activation unavailable: {exc}")

    def _handle_wake_command(self, command: str, transcript: str) -> None:
        if not command:
            log.info("Wake phrase detected without a follow-up command")
            self._publish_log("system", "Wake phrase detected, but no command followed it.")
            return
        log.info("Wake phrase detected: %s", transcript)
        self.submit_voice_transcript(command, raw_transcript=transcript)

    def _set_voice_runtime(self, state: str, detail: str) -> None:
        with self._voice_runtime_lock:
            self._voice_runtime_state = state
            self._voice_runtime_detail = detail
        self.state.set_status("voice", state, detail)
        self._publish_status()

    def _normalize_user_text(self, text: str) -> str:
        cleaned = " ".join(text.strip().split())
        replacements = (
            (r"\bcloud code\b", "claude code"),
            (r"\bclawed code\b", "claude code"),
            (r"\bclaude\s+(?:dode|doe|ode|odes|node|noodles|coda|coat|coats|cold|mode|load)\b", "claude code"),
            (r"\bcloud\s+(?:code|codes|node|odes|noodles)\b", "claude code"),
            (r"\bpower shell\b", "powershell"),
            (r"\bvisual studio\b", "visual studio code"),
        )
        for pattern, replacement in replacements:
            cleaned = re.sub(pattern, replacement, cleaned, flags=re.IGNORECASE)
        launch_match = re.match(
            r"^(?P<prefix>(?:please\s+)?(?:open|launch|start|run))\s+(?P<target>.+)$",
            cleaned,
            flags=re.IGNORECASE,
        )
        if launch_match:
            target = launch_match.group("target").strip()
            canonical = self.actions.canonicalize_launch_target(target)
            if canonical is not None:
                cleaned = f"{launch_match.group('prefix')} {canonical}"
        else:
            canonical = self.actions.canonicalize_launch_target(cleaned)
            if canonical is not None:
                cleaned = canonical
        return cleaned.strip()

    def _looks_like_open_target(self, target: str) -> bool:
        if target.startswith(("http://", "https://", "www.")):
            return True
        if re.match(r"^[a-zA-Z]:\\", target):
            return True
        if "/" in target or "\\" in target:
            return True
        return self._has_file_extension(target)

    @staticmethod
    def _has_file_extension(text: str) -> bool:
        parts = text.rsplit(".", 1)
        if len(parts) != 2:
            return False
        return bool(parts[0]) and bool(parts[1]) and " " not in parts[1]

    def _desktop_context_text(self) -> str:
        with self._desktop_context_lock:
            snapshot = self._desktop_context
        return snapshot.summary

    def _extract_browser_intent(self, text: str) -> tuple[str, str] | None:
        patterns = (
            r"^(?:please\s+)?(?:open|launch|start|run)\s+(?P<target>.+?)\s+(?:on|in)\s+(?P<browser>google chrome|chrome|microsoft edge|edge)$",
            r"^(?:please\s+)?(?:open|launch|start|run)\s+(?P<browser>google chrome|chrome|microsoft edge|edge)\s+(?:and\s+)?(?:go to\s+)?(?P<target>.+)$",
        )
        for pattern in patterns:
            match = re.match(pattern, text, flags=re.IGNORECASE)
            if not match:
                continue
            target = self._normalize_user_text(match.group("target"))
            browser = self._normalize_user_text(match.group("browser"))
            return target, browser
        return None

    def _extract_claude_task(self, text: str) -> str:
        patterns = (
            r"^(?:please\s+)?(?P<task>.+?)\s+in\s+claude\s+code$",
            r"^(?:please\s+)?(?P<task>.+?)\s+(?:using|with|via)\s+claude\s+code$",
            r"^(?:please\s+)?(?:use|ask)\s+claude\s+code\s+to\s+(?P<task>.+)$",
            r"^(?:please\s+)?(?:have|get)\s+claude\s+code\s+to\s+(?P<task>.+)$",
            r"^(?:please\s+)?(?:open|launch|start)\s+claude\s+code\s+(?:and\s+)?(?P<task>.+)$",
        )
        for pattern in patterns:
            match = re.match(pattern, text, flags=re.IGNORECASE)
            if not match:
                continue
            task = self._normalize_user_text(match.group("task")).strip(" .")
            if task:
                return task
        return ""
