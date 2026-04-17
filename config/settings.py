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
    window_title: str = "JARVIS // LOCAL CONSOLE"
    theme_accent: str = "#ffb000"
    theme_background: str = "#050505"
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen2.5:3b"
    ollama_timeout_seconds: float = 45.0
    ollama_num_ctx: int = 4096
    ollama_num_predict: int = 320
    whisper_model_size: str = "tiny.en"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"
    voice_record_seconds: int = 4
    voice_sample_rate: int = 16000
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
            "whisper_model_size": self.whisper_model_size,
            "whisper_device": self.whisper_device,
            "whisper_compute_type": self.whisper_compute_type,
            "voice_record_seconds": self.voice_record_seconds,
            "voice_sample_rate": self.voice_sample_rate,
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

        if settings.config_file.exists():
            try:
                raw = json.loads(settings.config_file.read_text(encoding="utf-8"))
                for key, value in raw.items():
                    if hasattr(settings, key):
                        setattr(settings, key, value)
            except json.JSONDecodeError:
                pass

        env_overrides = {
            "JARVIS_OLLAMA_BASE_URL": "ollama_base_url",
            "JARVIS_OLLAMA_MODEL": "ollama_model",
            "JARVIS_WHISPER_MODEL": "whisper_model_size",
            "JARVIS_VOICE_SECONDS": "voice_record_seconds",
        }
        for env_name, attr_name in env_overrides.items():
            value = os.getenv(env_name)
            if not value:
                continue
            current = getattr(settings, attr_name)
            if isinstance(current, int):
                setattr(settings, attr_name, int(value))
            elif isinstance(current, float):
                setattr(settings, attr_name, float(value))
            else:
                setattr(settings, attr_name, value)

        settings.save()
        return settings
