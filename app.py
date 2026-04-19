from __future__ import annotations
import ctypes
import logging
import signal
import sys
import traceback
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMessageBox

from actions.registry import ActionRegistry
from actions.system_actions import SystemActions
from config.settings import AppSettings
from core.app_state import AppState
from core.event_bus import EventBus
from core.orchestrator import Orchestrator
from integrations.web_tools import ConstrainedWebTools
from integrations.windows_context import WindowsContextProbe
from integrations.windows_startup import WindowsStartupRegistration
from memory.store import MemoryStore
from providers.llm.ollama_provider import OllamaProvider
from resources import load_app_icon
from security.approvals import ApprovalManager
from security.audit import AuditLogger
from security.context_manager import ContextManager
from security.handoff import HandoffManager
from security.policy import PolicyEngine
from security.workspace import WorkspaceJail
from ui.main_window import MainWindow
from ui.system_tray import SystemTrayController
from voice.stt_whisper import WhisperSTT


log = logging.getLogger(__name__)


def launch_in_background(argv: list[str]) -> bool:
    return any(arg == "--background" for arg in argv[1:])


def configure_logging(log_file: Path | None) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]

    if log_file is not None:
        try:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            handlers.insert(0, logging.FileHandler(log_file, encoding="utf-8"))
        except OSError as exc:
            fallback_logger = logging.getLogger("jarvis.bootstrap")
            logging.basicConfig(
                level=logging.INFO,
                format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                handlers=handlers,
                force=True,
            )
            fallback_logger.warning("File logging unavailable at %s: %s", log_file, exc)
            return

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("huggingface_hub").setLevel(logging.WARNING)
    logging.getLogger("faster_whisper").setLevel(logging.WARNING)


def set_windows_app_id(app_id: str) -> None:
    if not sys.platform.startswith("win"):
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except Exception:
        log.debug("Failed to set AppUserModelID", exc_info=True)


def show_fatal_error(title: str, message: str, details: str = "") -> None:
    body = message if not details else f"{message}\n\n{details}"
    app = QApplication.instance()
    if app is not None:
        QMessageBox.critical(None, title, body)
        return

    if sys.platform.startswith("win"):
        try:
            ctypes.windll.user32.MessageBoxW(None, body, title, 0x10)
            return
        except Exception:
            log.debug("Native fatal error dialog failed", exc_info=True)

    print(f"{title}: {body}", file=sys.stderr)


class SingleInstanceGuard(QObject):
    activated = Signal()

    def __init__(self, server_name: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.server_name = server_name
        self._server = QLocalServer(self)
        self._server.newConnection.connect(self._handle_new_connection)
        self._already_running = False
        self._listening = False

    @property
    def already_running(self) -> bool:
        return self._already_running

    def acquire(self) -> bool:
        probe = QLocalSocket(self)
        probe.connectToServer(self.server_name)
        if probe.waitForConnected(250):
            self._already_running = True
            probe.write(b"show")
            probe.flush()
            probe.waitForBytesWritten(250)
            probe.disconnectFromServer()
            return False

        QLocalServer.removeServer(self.server_name)
        self._listening = self._server.listen(self.server_name)
        if not self._listening:
            log.error("Failed to listen on single-instance server %s: %s", self.server_name, self._server.errorString())
        return self._listening

    def close(self) -> None:
        if not self._listening:
            return
        self._server.close()
        QLocalServer.removeServer(self.server_name)
        self._listening = False

    def _handle_new_connection(self) -> None:
        while self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            if socket is not None:
                socket.readAll()
                socket.disconnectFromServer()
                socket.deleteLater()
        self.activated.emit()


class AppBootstrap:
    def __init__(self) -> None:
        self._start_in_background = launch_in_background(sys.argv)
        self.settings: AppSettings | None = None
        self.app: QApplication | None = None
        self.bus: EventBus | None = None
        self.state: AppState | None = None
        self.memory: MemoryStore | None = None
        self.jail: WorkspaceJail | None = None
        self.policy: PolicyEngine | None = None
        self.approvals: ApprovalManager | None = None
        self.audit: AuditLogger | None = None
        self.context_manager: ContextManager | None = None
        self.llm: OllamaProvider | None = None
        self.voice: WhisperSTT | None = None
        self.actions: SystemActions | None = None
        self.registry: ActionRegistry | None = None
        self.context_probe: WindowsContextProbe | None = None
        self.orchestrator: Orchestrator | None = None
        self.startup_manager: WindowsStartupRegistration | None = None
        self.web_tools: ConstrainedWebTools | None = None
        self.window: MainWindow | None = None
        self.tray: SystemTrayController | None = None
        self.dispatch_timer: QTimer | None = None
        self.health_timer: QTimer | None = None
        self.context_timer: QTimer | None = None
        self.instance_guard: SingleInstanceGuard | None = None
        self._shutdown_started = False

    def run(self) -> int:
        configure_logging(None)

        try:
            self.settings = AppSettings.load()
            configure_logging(self.settings.log_file)
            set_windows_app_id(self.settings.app_id)
            for warning in self.settings.validation_warnings:
                log.warning("Settings validation: %s", warning)
            self._create_application()
            self._acquire_single_instance()
            self._create_runtime_objects()
            self._wire_ui()
            self._create_timers()
            self._install_signal_handling()
            self._finalize_startup()
            log.info("Startup sequence complete")
            return self.app.exec()
        except Exception as exc:
            log.exception("Fatal startup failure")
            show_fatal_error("JARVIS failed to start", "A fatal startup error occurred.", str(exc))
            log.debug("Startup traceback:\n%s", traceback.format_exc())
            return 1
        finally:
            self.shutdown()

    def shutdown(self) -> None:
        if self._shutdown_started:
            return
        self._shutdown_started = True
        log.info("Shutting down application")

        for timer_attr in ("dispatch_timer", "health_timer", "context_timer"):
            timer = getattr(self, timer_attr)
            if timer is not None:
                timer.stop()
                timer.deleteLater()
                setattr(self, timer_attr, None)

        if self.tray is not None:
            self.tray.shutdown()
            self.tray = None

        if self.orchestrator is not None:
            try:
                self.orchestrator.shutdown()
            except Exception:
                log.exception("Orchestrator shutdown failed")
            finally:
                self.orchestrator = None

        if self.instance_guard is not None:
            self.instance_guard.close()
            self.instance_guard = None

    def _create_application(self) -> None:
        if QApplication.instance() is not None:
            raise RuntimeError("A QApplication instance already exists.")

        self.app = QApplication(sys.argv)
        self.app.aboutToQuit.connect(self.shutdown)
        self.app.setApplicationName(self.settings.app_name)
        self.app.setApplicationDisplayName(self.settings.app_name)
        self.app.setOrganizationName("ethanplusai")
        self.app.setDesktopFileName(self.settings.app_id)
        self.app.setQuitOnLastWindowClosed(False)

        icon = load_app_icon()
        if not icon.isNull():
            self.app.setWindowIcon(icon)

    def _acquire_single_instance(self) -> None:
        server_name = f"{self.settings.app_id}.instance"
        self.instance_guard = SingleInstanceGuard(server_name, self.app)
        self.instance_guard.activated.connect(self._handle_secondary_launch)
        if self.instance_guard.acquire():
            return

        if self.instance_guard.already_running:
            log.info("Another instance is already running. Requested focus and exiting.")
            raise SystemExit(0)

        raise RuntimeError(f"Unable to initialize the single-instance guard for {server_name}.")

    def _create_runtime_objects(self) -> None:
        self.bus = EventBus()
        self.state = AppState(max_logs=self.settings.max_console_blocks)
        self.memory = MemoryStore(self.settings.database_path)
        self.jail = WorkspaceJail(self.settings)
        self.approvals = ApprovalManager()
        self.audit = AuditLogger(self.settings.app_dir, debug_sensitive_logging=self.settings.debug_sensitive_logging)
        self.context_manager = ContextManager(self.settings, self.memory)
        self.llm = OllamaProvider(self.settings)
        self.voice = WhisperSTT(self.settings)
        self.actions = SystemActions(self.settings)
        self.web_tools = ConstrainedWebTools()
        self.startup_manager = WindowsStartupRegistration(self.settings.app_name, Path(__file__))
        self.startup_manager.sync_enabled(self.settings.start_on_login)
        self.registry = ActionRegistry(
            self.settings,
            self.actions,
            self.jail,
            HandoffManager(self.settings, self.jail, self.context_manager),
        )
        self.policy = PolicyEngine(self.settings, self.jail)
        self.context_probe = WindowsContextProbe()
        self.orchestrator = Orchestrator(
            self.settings,
            self.state,
            self.bus,
            self.memory,
            self.llm,
            self.voice,
            self.actions,
            self.registry,
            self.policy,
            self.approvals,
            self.audit,
            self.context_manager,
            self.jail,
            self.context_probe,
            self.web_tools,
            self.startup_manager,
        )

        icon = load_app_icon()
        self.window = MainWindow(self.settings)
        if not icon.isNull():
            self.window.setWindowIcon(icon)

        self.tray = SystemTrayController(
            self.app,
            self.window,
            icon=icon,
            tooltip=self.settings.app_name,
            pause_callback=self.orchestrator.toggle_autonomy_pause,
            stop_callback=self.orchestrator.stop_active_task,
            show_approvals_callback=None,
            voice_capture_callback=self.orchestrator.submit_voice_capture,
            health_check_callback=self.orchestrator.refresh_health,
            open_claude_callback=lambda: self.orchestrator.submit_text("open claude code"),
        )
        self.orchestrator.set_notifier(self.tray)
        tray_available = self.tray.is_available()
        self.window.set_hide_to_tray(tray_available)
        self.app.setQuitOnLastWindowClosed(not tray_available)
        if not tray_available:
            log.warning("System tray is unavailable. Window close will exit the application.")

    def _wire_ui(self) -> None:
        self.bus.subscribe("log", self.window.append_log)
        self.bus.subscribe("status", self.window.update_statuses)
        self.bus.subscribe("context", self.window.update_context)
        self.bus.subscribe("policy", self.window.update_policy_state)
        self.bus.subscribe("approvals", self.window.update_approval_state)

        self.window.command_input.submitted.connect(self.orchestrator.submit_text)
        self.window.command_input.voice_requested.connect(self.orchestrator.submit_voice_capture)
        self.window.quick_command_requested.connect(self.orchestrator.submit_text)
        self.window.autonomy_mode_changed.connect(self.orchestrator.set_autonomy_mode)
        self.window.pause_requested.connect(self.orchestrator.toggle_autonomy_pause)
        self.window.deny_high_risk_requested.connect(self.orchestrator.toggle_deny_high_risk)
        self.window.stop_requested.connect(self.orchestrator.stop_active_task)
        self.window.approve_requested.connect(self.orchestrator.approve_pending)
        self.window.deny_requested.connect(self.orchestrator.deny_pending)
        self.window.clear_approvals_requested.connect(self.orchestrator.clear_pending_approvals)
        self.window.voice_toggle_requested.connect(self.orchestrator.toggle_voice_activation)
        self.window.startup_toggle_requested.connect(self.orchestrator.toggle_startup_on_login)

    def _create_timers(self) -> None:
        self.dispatch_timer = QTimer(self.app)
        self.dispatch_timer.setInterval(30)
        self.dispatch_timer.timeout.connect(self._dispatch_bus_events)

        self.health_timer = QTimer(self.app)
        self.health_timer.setInterval(15000)
        self.health_timer.timeout.connect(self._refresh_health)

        self.context_timer = QTimer(self.app)
        self.context_timer.setInterval(max(500, int(self.settings.desktop_context_poll_seconds * 1000)))
        self.context_timer.timeout.connect(self._refresh_context)

    def _install_signal_handling(self) -> None:
        if getattr(sys, "frozen", False):
            return
        if not hasattr(signal, "SIGINT"):
            return
        signal.signal(signal.SIGINT, self._handle_sigint)

    def _finalize_startup(self) -> None:
        self.window.update_statuses(self.state.snapshot_statuses())
        self.dispatch_timer.start()
        self.health_timer.start()
        if self.context_timer is not None:
            self.context_timer.start()
        if self._start_in_background and self.tray is not None and self.tray.is_available():
            self.window.hide()
            self.tray.sync_state()
            self.tray.notify(
                self.settings.app_name,
                "Started in the tray. Voice capture, health check, and Claude Code are available from the tray menu.",
            )
        else:
            self.window.show_and_focus()
        QTimer.singleShot(0, self._start_orchestrator)

    def _start_orchestrator(self) -> None:
        if self.orchestrator is not None:
            self.orchestrator.start()

    def _dispatch_bus_events(self) -> None:
        if self.bus is not None:
            self.bus.dispatch_pending()

    def _refresh_health(self) -> None:
        if self.orchestrator is not None:
            self.orchestrator.refresh_health()

    def _refresh_context(self) -> None:
        if self.orchestrator is not None:
            self.orchestrator.refresh_context()

    def _handle_secondary_launch(self) -> None:
        if self.window is not None:
            self.window.show_and_focus()
        if self.tray is not None:
            self.tray.sync_state()

    def _handle_sigint(self, signum, frame) -> None:
        del signum, frame
        log.info("SIGINT received, requesting shutdown")
        if self.app is not None:
            self.app.quit()


def main() -> int:
    bootstrap = AppBootstrap()
    try:
        return bootstrap.run()
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 0
        bootstrap.shutdown()
        return code


if __name__ == "__main__":
    raise SystemExit(main())
