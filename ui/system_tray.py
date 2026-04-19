from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, Qt, Signal, Slot
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap, QPen
from PySide6.QtWidgets import QMenu, QSystemTrayIcon


class SystemTrayController(QObject):
    notification_requested = Signal(str, str, str, int)

    def __init__(
        self,
        app,
        window,
        icon: QIcon | None = None,
        tooltip: str = "JARVIS Local",
        pause_callback: Callable[[], None] | None = None,
        stop_callback: Callable[[], None] | None = None,
        show_approvals_callback: Callable[[], None] | None = None,
        voice_capture_callback: Callable[[], None] | None = None,
        health_check_callback: Callable[[], None] | None = None,
        open_claude_callback: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(window)
        self.app = app
        self.window = window
        self._available = QSystemTrayIcon.isSystemTrayAvailable()
        self.tray = QSystemTrayIcon(icon if icon is not None and not icon.isNull() else self._build_icon(), window)
        self.tray.setToolTip(tooltip)
        self._pause_callback = pause_callback
        self._stop_callback = stop_callback
        self._show_approvals_callback = show_approvals_callback
        self._voice_capture_callback = voice_capture_callback
        self._health_check_callback = health_check_callback
        self._open_claude_callback = open_claude_callback

        menu = QMenu()
        self.toggle_action = QAction("Hide", menu)
        self.voice_action = QAction("Capture voice", menu)
        self.health_action = QAction("Health check", menu)
        self.claude_action = QAction("Open Claude Code", menu)
        self.pause_action = QAction("Pause autonomy", menu)
        self.stop_action = QAction("Emergency stop", menu)
        self.approvals_action = QAction("Show approvals", menu)
        self.quit_action = QAction("Quit", menu)

        self.toggle_action.triggered.connect(self.toggle_window)
        self.voice_action.triggered.connect(self._handle_voice_capture)
        self.health_action.triggered.connect(self._handle_health_check)
        self.claude_action.triggered.connect(self._handle_open_claude)
        self.pause_action.triggered.connect(self._handle_pause)
        self.stop_action.triggered.connect(self._handle_stop)
        self.approvals_action.triggered.connect(self._handle_show_approvals)
        self.quit_action.triggered.connect(self.quit_application)

        menu.addAction(self.toggle_action)
        menu.addAction(self.voice_action)
        menu.addAction(self.health_action)
        menu.addAction(self.claude_action)
        menu.addSeparator()
        menu.addAction(self.pause_action)
        menu.addAction(self.stop_action)
        menu.addAction(self.approvals_action)
        menu.addSeparator()
        menu.addAction(self.quit_action)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._handle_activation)
        self.notification_requested.connect(self._show_notification, Qt.ConnectionType.QueuedConnection)

        if self._available:
            self.tray.show()

    def is_available(self) -> bool:
        return self._available

    def toggle_window(self) -> None:
        if self.window.isVisible():
            self.window.hide()
            self.toggle_action.setText("Show")
            return

        self.window.show_and_focus()
        self.toggle_action.setText("Hide")

    def quit_application(self) -> None:
        self.window.prepare_to_quit()
        self.shutdown()
        self.app.quit()

    def sync_state(self) -> None:
        self.toggle_action.setText("Hide" if self.window.isVisible() else "Show")

    def notify(self, title: str, message: str, level: str = "info", timeout_ms: int = 5000) -> None:
        if not self._available:
            return
        self.notification_requested.emit(title, message, level, timeout_ms)

    def shutdown(self) -> None:
        if self.tray is not None:
            self.tray.hide()

    def _handle_activation(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.toggle_window()

    def _handle_pause(self) -> None:
        if self._pause_callback is not None:
            self._pause_callback()

    def _handle_voice_capture(self) -> None:
        if self._voice_capture_callback is not None:
            self._voice_capture_callback()

    def _handle_health_check(self) -> None:
        if self._health_check_callback is not None:
            self._health_check_callback()

    def _handle_open_claude(self) -> None:
        if self._open_claude_callback is not None:
            self._open_claude_callback()

    def _handle_stop(self) -> None:
        if self._stop_callback is not None:
            self._stop_callback()

    def _handle_show_approvals(self) -> None:
        self.window.show_and_focus()
        if self._show_approvals_callback is not None:
            self._show_approvals_callback()

    def _build_icon(self) -> QIcon:
        pixmap = QPixmap(64, 64)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(pixmap.rect(), QColor(8, 8, 8, 220))

        pen = QPen(QColor("#ffb000"))
        pen.setWidth(3)
        painter.setPen(pen)
        painter.drawRoundedRect(8, 8, 48, 48, 8, 8)
        painter.drawLine(18, 24, 46, 24)
        painter.drawLine(18, 34, 40, 34)
        painter.drawLine(18, 44, 32, 44)
        painter.end()

        return QIcon(pixmap)

    @Slot(str, str, str, int)
    def _show_notification(self, title: str, message: str, level: str, timeout_ms: int) -> None:
        if not self._available:
            return
        icon = {
            "info": QSystemTrayIcon.MessageIcon.Information,
            "warn": QSystemTrayIcon.MessageIcon.Warning,
            "error": QSystemTrayIcon.MessageIcon.Critical,
        }.get(level, QSystemTrayIcon.MessageIcon.NoIcon)
        self.tray.showMessage(title, message, icon, timeout_ms)
