from __future__ import annotations

import ctypes
import logging
import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from actions.system_actions import SystemActions
from config.settings import AppSettings
from core.app_state import AppState
from core.event_bus import EventBus
from core.orchestrator import Orchestrator
from memory.store import MemoryStore
from providers.llm.ollama_provider import OllamaProvider
from ui.main_window import MainWindow
from ui.system_tray import SystemTrayController
from voice.stt_whisper import WhisperSTT


def configure_logging(log_file) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def set_windows_app_id(app_id: str) -> None:
    if not sys.platform.startswith("win"):
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except Exception:
        pass


def main() -> int:
    settings = AppSettings.load()
    configure_logging(settings.log_file)
    set_windows_app_id(settings.app_id)

    app = QApplication(sys.argv)
    app.setApplicationName(settings.app_name)
    app.setQuitOnLastWindowClosed(False)

    bus = EventBus()
    state = AppState(max_logs=settings.max_console_blocks)
    memory = MemoryStore(settings.database_path)
    llm = OllamaProvider(settings)
    voice = WhisperSTT(settings)
    actions = SystemActions()
    orchestrator = Orchestrator(settings, state, bus, memory, llm, voice, actions)

    window = MainWindow(settings)
    tray = SystemTrayController(app, window)
    window.set_hide_to_tray(tray.is_available())

    bus.subscribe("log", window.append_log)
    bus.subscribe("status", window.update_statuses)

    window.command_input.submitted.connect(orchestrator.submit_text)
    window.command_input.voice_requested.connect(orchestrator.submit_voice_capture)

    dispatch_timer = QTimer()
    dispatch_timer.timeout.connect(lambda: bus.dispatch_pending())
    dispatch_timer.start(30)

    health_timer = QTimer()
    health_timer.timeout.connect(orchestrator.refresh_health)
    health_timer.start(10000)

    window.update_statuses(state.snapshot_statuses())
    window.show()
    orchestrator.start()

    exit_code = app.exec()
    orchestrator.shutdown()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
