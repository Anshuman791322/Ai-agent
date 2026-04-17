from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent, QFont
from PySide6.QtWidgets import QFrame, QLabel, QMainWindow, QVBoxLayout, QWidget

from config.settings import AppSettings
from ui.widgets.command_input import CommandInputWidget
from ui.widgets.console_log import ConsoleLogWidget
from ui.widgets.scanline_overlay import ScanlineOverlay
from ui.widgets.status_badges import StatusBadgesWidget


class MainWindow(QMainWindow):
    def __init__(self, settings: AppSettings, parent=None) -> None:
        super().__init__(parent)
        self.settings = settings
        self._hide_to_tray = True
        self._allow_close = False

        self.setWindowTitle(self.settings.window_title)
        self.resize(1180, 760)
        self.setMinimumSize(960, 620)

        font = QFont("Cascadia Mono")
        if not font.exactMatch():
            font = QFont("Consolas")
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.setFont(font)

        central = QWidget(self)
        central.setObjectName("mainWindowRoot")
        self.setCentralWidget(central)

        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(18, 18, 18, 18)
        root_layout.setSpacing(12)

        header = QFrame(central)
        header.setObjectName("headerFrame")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(2)

        title = QLabel("JARVIS // WINDOWS NODE", header)
        title.setObjectName("titleLabel")
        subtitle = QLabel("LOCAL-FIRST // OLLAMA // WHISPER // SYSTEM TRAY ONLINE", header)
        subtitle.setObjectName("subtitleLabel")
        header_layout.addWidget(title)
        header_layout.addWidget(subtitle)

        self.status_badges = StatusBadgesWidget(central)
        self.console_log = ConsoleLogWidget(max_blocks=self.settings.max_console_blocks, parent=central)
        self.command_input = CommandInputWidget(central)

        root_layout.addWidget(header)
        root_layout.addWidget(self.status_badges)
        root_layout.addWidget(self.console_log, 1)
        root_layout.addWidget(self.command_input)

        self.scanline_overlay = ScanlineOverlay(central)
        self.scanline_overlay.raise_()

        self._apply_styles()

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QWidget#mainWindowRoot {
                background-color: #050505;
                color: #ffc14d;
            }
            QFrame#headerFrame {
                background: transparent;
                border: 1px solid rgba(255, 176, 0, 0.16);
                border-radius: 8px;
                padding: 8px;
            }
            QLabel#titleLabel {
                color: #ffb000;
                font-size: 24px;
                font-weight: 700;
                letter-spacing: 2px;
            }
            QLabel#subtitleLabel {
                color: rgba(255, 193, 77, 0.68);
                font-size: 11px;
                letter-spacing: 2px;
            }
            QFrame#consoleFrame {
                border: 1px solid rgba(255, 176, 0, 0.2);
                border-radius: 8px;
                background-color: rgba(6, 6, 6, 0.92);
            }
            QPlainTextEdit#consoleView {
                background-color: rgba(0, 0, 0, 0.8);
                color: #ffcc70;
                border: none;
                padding: 12px;
                selection-background-color: rgba(255, 176, 0, 0.28);
            }
            QFrame#commandInputFrame {
                border: 1px solid rgba(255, 176, 0, 0.2);
                border-radius: 8px;
                background-color: rgba(10, 10, 10, 0.94);
                padding: 8px;
            }
            QLineEdit#commandLineEdit {
                background-color: rgba(0, 0, 0, 0.88);
                border: 1px solid rgba(255, 176, 0, 0.25);
                color: #ffe1a3;
                padding: 12px;
                border-radius: 6px;
            }
            QPushButton#commandSendButton, QPushButton#commandVoiceButton {
                background-color: rgba(255, 176, 0, 0.08);
                border: 1px solid rgba(255, 176, 0, 0.32);
                color: #ffb000;
                padding: 10px 14px;
                border-radius: 6px;
                min-width: 88px;
            }
            QPushButton#commandSendButton:hover, QPushButton#commandVoiceButton:hover {
                background-color: rgba(255, 176, 0, 0.16);
            }
            QFrame#statusBadgesFrame {
                background: transparent;
            }
            QLabel#statusBadge {
                border-radius: 11px;
                padding: 6px 10px;
                font-size: 11px;
                letter-spacing: 1px;
                border: 1px solid rgba(255, 176, 0, 0.22);
                background-color: rgba(255, 176, 0, 0.05);
                color: #ffcc70;
            }
            QLabel#statusBadge[state="ok"] {
                border: 1px solid rgba(89, 255, 149, 0.3);
                background-color: rgba(89, 255, 149, 0.08);
                color: #8cffb1;
            }
            QLabel#statusBadge[state="warn"] {
                border: 1px solid rgba(255, 184, 77, 0.35);
                background-color: rgba(255, 184, 77, 0.12);
                color: #ffd08c;
            }
            QLabel#statusBadge[state="error"] {
                border: 1px solid rgba(255, 92, 92, 0.35);
                background-color: rgba(255, 92, 92, 0.1);
                color: #ff8d8d;
            }
            QLabel#statusBadge[state="busy"] {
                border: 1px solid rgba(77, 214, 255, 0.35);
                background-color: rgba(77, 214, 255, 0.1);
                color: #88e7ff;
            }
            """
        )

    def set_hide_to_tray(self, enabled: bool) -> None:
        self._hide_to_tray = enabled

    def append_log(self, payload: dict) -> None:
        self.console_log.append_entry(payload)

    def update_statuses(self, payload: dict) -> None:
        self.status_badges.update_badges(payload)

    def prepare_to_quit(self) -> None:
        self._allow_close = True

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.centralWidget() is not None:
            self.scanline_overlay.setGeometry(self.centralWidget().rect())
            self.scanline_overlay.raise_()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._hide_to_tray and not self._allow_close:
            self.hide()
            event.ignore()
            return
        super().closeEvent(event)
