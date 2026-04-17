from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap, QPen
from PySide6.QtWidgets import QMenu, QSystemTrayIcon


class SystemTrayController:
    def __init__(self, app, window) -> None:
        self.app = app
        self.window = window
        self.tray = QSystemTrayIcon(self._build_icon(), window)
        self.tray.setToolTip("JARVIS Local")

        menu = QMenu()
        self.toggle_action = QAction("Hide", menu)
        self.quit_action = QAction("Quit", menu)

        self.toggle_action.triggered.connect(self.toggle_window)
        self.quit_action.triggered.connect(self.quit_application)

        menu.addAction(self.toggle_action)
        menu.addSeparator()
        menu.addAction(self.quit_action)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._handle_activation)

        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()

    def is_available(self) -> bool:
        return QSystemTrayIcon.isSystemTrayAvailable()

    def toggle_window(self) -> None:
        if self.window.isVisible():
            self.window.hide()
            self.toggle_action.setText("Show")
            return

        self.window.show()
        self.window.raise_()
        self.window.activateWindow()
        self.toggle_action.setText("Hide")

    def quit_application(self) -> None:
        self.window.prepare_to_quit()
        self.tray.hide()
        self.app.quit()

    def _handle_activation(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.toggle_window()

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
