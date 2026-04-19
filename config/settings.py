from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


def _default_app_dir() -> Path:
    local_app_data = os.getenv("LOCALAPPDATA")
    base = Path(local_app_data) if local_app_data else Path.home() / ".jarvis_windows_local"
    return base / "JarvisWindowsLocal"


@dataclass
class AppSettings:
    app_name: str = "JARVIS Local"
    app_id: str = "ethanplusai.jarvis.local.windows"
    window_title: str = "JARVIS // WINDOWS COMMAND CENTER"
    theme_accent: str = "#ffb000"
    theme_background: str = "#050505"
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen3.5:0.8b"
    ollama_timeout_seconds: float = 30.0
    ollama_num_ctx: int = 2048
    ollama_num_predict: int = 160
    ollama_keep_alive: str = "30m"
    ollama_auto_start: bool = True
    ollama_auto_pull: bool = True
    ollama_start_timeout_seconds: float = 20.0
    whisper_model_size: str = "base.en"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"
    whisper_beam_size: int = 2
    whisper_best_of: int = 2
    whisper_command_beam_size: int = 1
    whisper_command_best_of: int = 1
    whisper_preload_on_startup: bool = True
    whisper_initial_prompt: str = (
        "This is a Windows desktop assistant command. Important phrases include "
        "Jarvis, Claude Code, PowerShell, File Explorer, Ollama, Visual Studio Code, and Chrome."
    )
    whisper_hotwords: list[str] = field(
        default_factory=lambda: [
            "Jarvis",
            "Claude Code",
            "Claude",
            "PowerShell",
            "File Explorer",
            "Ollama",
            "Visual Studio Code",
            "Chrome",
        ]
    )
    voice_record_seconds: int = 3
    voice_sample_rate: int = 16000
    voice_activation_enabled: bool = True
    voice_wake_phrase: str = "jarvis"
    voice_activation_engine: str = "transcript"
    voice_command_arm_seconds: float = 4.0
    voice_wake_threshold: float = 0.34
    voice_wake_patience: int = 1
    voice_wake_debounce_seconds: float = 0.45
    voice_activation_energy_threshold: float = 0.012
    voice_activation_preroll_seconds: float = 0.2
    voice_activation_min_seconds: float = 0.45
    voice_activation_max_seconds: float = 4.5
    voice_activation_end_silence_seconds: float = 0.3
    voice_activation_min_speech_blocks: int = 2
    claude_code_workspace: str = r"C:\Users\anshu\Downloads\Codex"
    desktop_context_enabled: bool = True
    desktop_context_poll_seconds: float = 2.0
    memory_history_limit: int = 12
    max_console_blocks: int = 800
    app_dir: Path = field(default_factory=_default_app_dir)

    def ensure_directories(self) -> None:
        self.app_dir.mkdir(parents=True, exist_ok=True)

    @property
    def config_file(self) -> Path:
        return self.app_dir / "settings.json"

    @property
    def database_path(self) -> Path:
        return self.app_dir / "jarvis_local.db"

    @property
    def log_file(self) -> Path:
        return self.app_dir / "jarvis.log"

    @property
    def system_prompt(self) -> str:
        return (
            "You are JARVIS, a Windows-first local desktop assistant running entirely on the user's machine. "
            "Keep answers direct, concise, and useful. Use Windows terminology. "
            "Prefer short paragraphs over bullet spam. "
            "If a task depends on an unavailable local subsystem, say what is offline and what the user can do next. "
            "Do not invent files, apps, or command output."
        )

    def to_json_dict(self) -> dict:
        return {
            "app_name": self.app_name,
            "app_id": self.app_id,
            "window_title": self.window_title,
            "theme_accent": self.theme_accent,
            "theme_background": self.theme_background,
            "ollama_base_url": self.ollama_base_url,
            "ollama_model": self.ollama_model,
            "ollama_timeout_seconds": self.ollama_timeout_seconds,
            "ollama_num_ctx": self.ollama_num_ctx,
            "ollama_num_predict": self.ollama_num_predict,
            "ollama_keep_alive": self.ollama_keep_alive,
            "ollama_auto_start": self.ollama_auto_start,
            "ollama_auto_pull": self.ollama_auto_pull,
            "ollama_start_timeout_seconds": self.ollama_start_timeout_seconds,
            "whisper_model_size": self.whisper_model_size,
            "whisper_device": self.whisper_device,
            "whisper_compute_type": self.whisper_compute_type,
            "whisper_beam_size": self.whisper_beam_size,
            "whisper_best_of": self.whisper_best_of,
            "whisper_command_beam_size": self.whisper_command_beam_size,
            "whisper_command_best_of": self.whisper_command_best_of,
            "whisper_preload_on_startup": self.whisper_preload_on_startup,
            "whisper_initial_prompt": self.whisper_initial_prompt,
            "whisper_hotwords": self.whisper_hotwords,
            "voice_record_seconds": self.voice_record_seconds,
            "voice_sample_rate": self.voice_sample_rate,
            "voice_activation_enabled": self.voice_activation_enabled,
            "voice_wake_phrase": self.voice_wake_phrase,
            "voice_activation_engine": self.voice_activation_engine,
            "voice_command_arm_seconds": self.voice_command_arm_seconds,
            "voice_wake_threshold": self.voice_wake_threshold,
            "voice_wake_patience": self.voice_wake_patience,
            "voice_wake_debounce_seconds": self.voice_wake_debounce_seconds,
            "voice_activation_energy_threshold": self.voice_activation_energy_threshold,
            "voice_activation_preroll_seconds": self.voice_activation_preroll_seconds,
            "voice_activation_min_seconds": self.voice_activation_min_seconds,
            "voice_activation_max_seconds": self.voice_activation_max_seconds,
            "voice_activation_end_silence_seconds": self.voice_activation_end_silence_seconds,
            "voice_activation_min_speech_blocks": self.voice_activation_min_speech_blocks,
            "claude_code_workspace": self.claude_code_workspace,
            "desktop_context_enabled": self.desktop_context_enabled,
            "desktop_context_poll_seconds": self.desktop_context_poll_seconds,
            "memory_history_limit": self.memory_history_limit,
            "max_console_blocks": self.max_console_blocks,
        }

    def save(self) -> None:
        self.ensure_directories()
        self.config_file.write_text(json.dumps(self.to_json_dict(), indent=2), encoding="utf-8")

    @classmethod
    def load(cls) -> "AppSettings":
        settings = cls()
        settings.ensure_directories()

        loaded_config: dict = {}
        if settings.config_file.exists():
            try:
                loaded_config = json.loads(settings.config_file.read_text(encoding="utf-8"))
                for key, value in loaded_config.items():
                    if hasattr(settings, key):
                        setattr(settings, key, value)
            except json.JSONDecodeError:
                pass

        if (
            loaded_config
            and loaded_config.get("whisper_model_size") == "tiny.en"
            and "whisper_beam_size" not in loaded_config
        ):
            settings.whisper_model_size = "base.en"
            settings.whisper_beam_size = 5
            settings.whisper_best_of = 5

        if loaded_config and loaded_config.get("window_title") == "JARVIS // LOCAL CONSOLE":
            settings.window_title = "JARVIS // WINDOWS COMMAND CENTER"

        if loaded_config and loaded_config.get("ollama_model") == "qwen2.5:3b":
            settings.ollama_model = "qwen3.5:0.8b"

        if loaded_config and loaded_config.get("ollama_num_ctx") == 4096:
            settings.ollama_num_ctx = 2048

        if loaded_config and loaded_config.get("ollama_num_predict") == 320:
            settings.ollama_num_predict = 160

        if loaded_config and loaded_config.get("voice_record_seconds") == 4:
            settings.voice_record_seconds = 3

        if loaded_config and "voice_activation_engine" not in loaded_config:
            settings.voice_activation_engine = "transcript"
            settings.voice_wake_threshold = 0.42
            settings.voice_wake_patience = 1
            settings.voice_wake_debounce_seconds = 1.2

        if loaded_config and loaded_config.get("voice_activation_engine") == "openwakeword":
            settings.voice_activation_engine = "transcript"

        if loaded_config and loaded_config.get("whisper_beam_size") == 5:
            settings.whisper_beam_size = 2

        if loaded_config and loaded_config.get("whisper_best_of") == 5:
            settings.whisper_best_of = 2

        if loaded_config and loaded_config.get("voice_wake_threshold") == 0.42:
            settings.voice_wake_threshold = 0.34

        if loaded_config and loaded_config.get("voice_wake_debounce_seconds") == 1.2:
            settings.voice_wake_debounce_seconds = 0.8

        if loaded_config and loaded_config.get("voice_wake_debounce_seconds") == 0.8:
            settings.voice_wake_debounce_seconds = 0.45

        if loaded_config and loaded_config.get("voice_activation_energy_threshold") == 0.015:
            settings.voice_activation_energy_threshold = 0.012

        if loaded_config and loaded_config.get("voice_activation_preroll_seconds") == 0.3:
            settings.voice_activation_preroll_seconds = 0.2

        if loaded_config and loaded_config.get("voice_activation_min_seconds") == 0.7:
            settings.voice_activation_min_seconds = 0.45

        if loaded_config and loaded_config.get("voice_activation_max_seconds") == 8.0:
            settings.voice_activation_max_seconds = 6.0

        if loaded_config and loaded_config.get("voice_activation_max_seconds") == 6.0:
            settings.voice_activation_max_seconds = 4.5

        if loaded_config and loaded_config.get("voice_activation_end_silence_seconds") == 1.0:
            settings.voice_activation_end_silence_seconds = 0.45

        if loaded_config and loaded_config.get("voice_activation_end_silence_seconds") == 0.45:
            settings.voice_activation_end_silence_seconds = 0.3

        if loaded_config and loaded_config.get("voice_activation_min_speech_blocks") == 3:
            settings.voice_activation_min_speech_blocks = 2

        env_overrides = {
            "JARVIS_OLLAMA_BASE_URL": "ollama_base_url",
            "JARVIS_OLLAMA_MODEL": "ollama_model",
            "JARVIS_WHISPER_MODEL": "whisper_model_size",
            "JARVIS_VOICE_SECONDS": "voice_record_seconds",
            "JARVIS_VOICE_WAKE_PHRASE": "voice_wake_phrase",
        }
        for env_name, attr_name in env_overrides.items():
            value = os.getenv(env_name)
            if not value:
                continue
            current = getattr(settings, attr_name)
            if isinstance(current, bool):
                setattr(settings, attr_name, value.lower() in {"1", "true", "yes", "on"})
            elif isinstance(current, int):
                setattr(settings, attr_name, int(value))
            elif isinstance(current, float):
                setattr(settings, attr_name, float(value))
            else:
                setattr(settings, attr_name, value)

        settings.save()
        return settings
