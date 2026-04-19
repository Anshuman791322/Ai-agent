from __future__ import annotations

from functools import partial

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QCloseEvent, QFont
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from config.settings import AppSettings
from ui.widgets.command_input import CommandInputWidget
from ui.widgets.console_log import ConsoleLogWidget
from ui.widgets.scanline_overlay import ScanlineOverlay
from ui.widgets.status_badges import StatusBadgesWidget


class MainWindow(QMainWindow):
    quick_command_requested = Signal(str)

    def __init__(self, settings: AppSettings, parent=None) -> None:
        super().__init__(parent)
        self.settings = settings
        self._hide_to_tray = True
        self._allow_close = False
        self._status_detail_labels: dict[str, QLabel] = {}

        self.setWindowTitle(self.settings.window_title)
        screen = QApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            width = max(1080, min(1320, available.width() - 48))
            height = max(680, min(820, available.height() - 72))
            self.resize(width, height)
        else:
            self.resize(1320, 820)
        self.setMinimumSize(1080, 680)

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

        header = self._build_header(central)
        self.status_badges = StatusBadgesWidget(central)

        body_layout = QHBoxLayout()
        body_layout.setSpacing(12)

        left_column = QVBoxLayout()
        left_column.setSpacing(12)
        self.console_log = ConsoleLogWidget(max_blocks=self.settings.max_console_blocks, parent=central)
        left_column.addWidget(self.console_log, 1)

        right_container = QWidget(central)
        right_container.setObjectName("rightColumnContainer")
        right_column = QVBoxLayout(right_container)
        right_column.setSpacing(12)
        right_column.setContentsMargins(0, 0, 0, 0)
        right_column.addWidget(self._build_context_panel(central))
        right_column.addWidget(self._build_status_panel(central))
        right_column.addWidget(self._build_voice_panel(central))
        right_column.addWidget(self._build_quick_actions_panel(central))
        right_column.addStretch(1)

        right_scroll = QScrollArea(central)
        right_scroll.setObjectName("rightScrollArea")
        right_scroll.setWidgetResizable(True)
        right_scroll.setFrameShape(QFrame.Shape.NoFrame)
        right_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        right_scroll.setWidget(right_container)

        body_layout.addLayout(left_column, 4)
        body_layout.addWidget(right_scroll, 2)

        self.command_input = CommandInputWidget(central)

        root_layout.addWidget(header)
        root_layout.addWidget(self.status_badges)
        root_layout.addLayout(body_layout, 1)
        root_layout.addWidget(self.command_input)

        self.scanline_overlay = ScanlineOverlay(central)
        self.scanline_overlay.raise_()

        self._apply_styles()

    def _build_header(self, parent: QWidget) -> QFrame:
        header = QFrame(parent)
        header.setObjectName("headerFrame")

        layout = QVBoxLayout(header)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(4)

        title = QLabel("JARVIS // WINDOWS COMMAND CENTER", header)
        title.setObjectName("titleLabel")
        subtitle = QLabel(
            f"LOCAL-FIRST // ALWAYS-LISTENING // {self.settings.ollama_model.upper()} // {self.settings.whisper_model_size.upper()}",
            header,
        )
        subtitle.setObjectName("subtitleLabel")
        self.runtime_label = QLabel("Wake phrase online. Local systems are initializing.", header)
        self.runtime_label.setObjectName("runtimeLabel")

        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(self.runtime_label)
        return header

    def _build_context_panel(self, parent: QWidget) -> QFrame:
        frame = QFrame(parent)
        frame.setObjectName("infoPanel")

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        title = QLabel("Desktop context", frame)
        title.setObjectName("panelTitle")
        subtitle = QLabel("Windows awareness", frame)
        subtitle.setObjectName("panelAccent")
        self.context_summary_label = QLabel("Waiting for active window data.", frame)
        self.context_summary_label.setObjectName("panelBody")
        self.context_summary_label.setWordWrap(True)
        self.context_detail_label = QLabel(
            f"Claude workspace: {self.settings.claude_code_workspace}",
            frame,
        )
        self.context_detail_label.setObjectName("panelBodyMuted")
        self.context_detail_label.setWordWrap(True)

        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(self.context_summary_label)
        layout.addWidget(self.context_detail_label)
        return frame

    def _build_status_panel(self, parent: QWidget) -> QFrame:
        frame = QFrame(parent)
        frame.setObjectName("infoPanel")

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        title = QLabel("Subsystems", frame)
        title.setObjectName("panelTitle")
        layout.addWidget(title)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)

        for row, key in enumerate(("llm", "voice", "memory", "actions")):
            name_label = QLabel(key.upper(), frame)
            name_label.setObjectName("infoKey")
            detail_label = QLabel("waiting for health check", frame)
            detail_label.setObjectName("infoValue")
            detail_label.setWordWrap(True)
            self._status_detail_labels[key] = detail_label
            grid.addWidget(name_label, row, 0)
            grid.addWidget(detail_label, row, 1)

        layout.addLayout(grid)
        return frame

    def _build_voice_panel(self, parent: QWidget) -> QFrame:
        frame = QFrame(parent)
        frame.setObjectName("infoPanel")

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        title = QLabel("Voice monitor", frame)
        title.setObjectName("panelTitle")
        subtitle = QLabel("Wake phrase: Jarvis", frame)
        subtitle.setObjectName("panelAccent")
        self.voice_monitor_label = QLabel(
            "Always-listening mode is enabled. Say 'Jarvis', pause if you want, then speak your command. The PTT button is only a fallback.",
            frame,
        )
        self.voice_monitor_label.setObjectName("panelBody")
        self.voice_monitor_label.setWordWrap(True)

        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(self.voice_monitor_label)
        return frame

    def _build_quick_actions_panel(self, parent: QWidget) -> QFrame:
        frame = QFrame(parent)
        frame.setObjectName("infoPanel")

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        title = QLabel("Quick actions", frame)
        title.setObjectName("panelTitle")
        layout.addWidget(title)

        commands = (
            ("OPEN CLAUDE CODE", "open claude code"),
            ("OPEN EXPLORER", "open file explorer"),
            ("OPEN POWERSHELL", "open powershell"),
            ("HEALTH CHECK", "/health"),
        )
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)
        for index, (label, command) in enumerate(commands):
            button = QPushButton(label, frame)
            button.setObjectName("quickActionButton")
            button.clicked.connect(partial(self.quick_command_requested.emit, command))
            grid.addWidget(button, index // 2, index % 2)

        layout.addLayout(grid)

        return frame

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QWidget#mainWindowRoot {
                background-color: #050505;
                color: #ffc14d;
            }
            QFrame#headerFrame, QFrame#consoleFrame, QFrame#infoPanel, QFrame#commandInputFrame {
                border: 1px solid rgba(255, 176, 0, 0.18);
                border-radius: 10px;
                background-color: rgba(7, 7, 7, 0.92);
            }
            QScrollArea#rightScrollArea {
                background: transparent;
                border: none;
            }
            QWidget#qt_scrollarea_viewport, QWidget#rightColumnContainer {
                background: transparent;
            }
            QLabel#titleLabel {
                color: #ffb000;
                font-size: 26px;
                font-weight: 700;
                letter-spacing: 2px;
            }
            QLabel#subtitleLabel {
                color: rgba(255, 193, 77, 0.68);
                font-size: 11px;
                letter-spacing: 2px;
            }
            QLabel#runtimeLabel {
                color: #9ef0b3;
                font-size: 12px;
            }
            QLabel#panelTitle {
                color: #ffb000;
                font-size: 15px;
                font-weight: 700;
                letter-spacing: 1px;
            }
            QLabel#panelAccent {
                color: #8cffb1;
                font-size: 12px;
            }
            QLabel#panelBody, QLabel#infoValue {
                color: #f3d99a;
                font-size: 12px;
                line-height: 1.3em;
            }
            QLabel#panelBodyMuted {
                color: rgba(255, 210, 145, 0.62);
                font-size: 11px;
                line-height: 1.25em;
            }
            QLabel#infoKey {
                color: rgba(255, 193, 77, 0.75);
                font-size: 11px;
                letter-spacing: 1px;
            }
            QPlainTextEdit#consoleView {
                background-color: rgba(0, 0, 0, 0.82);
                color: #ffcc70;
                border: none;
                padding: 12px;
                selection-background-color: rgba(255, 176, 0, 0.28);
                font-size: 13px;
            }
            QLineEdit#commandLineEdit {
                background-color: rgba(0, 0, 0, 0.88);
                border: 1px solid rgba(255, 176, 0, 0.25);
                color: #ffe1a3;
                padding: 12px;
                border-radius: 6px;
                font-size: 13px;
            }
            QPushButton#commandSendButton, QPushButton#commandVoiceButton, QPushButton#quickActionButton {
                background-color: rgba(255, 176, 0, 0.08);
                border: 1px solid rgba(255, 176, 0, 0.32);
                color: #ffb000;
                padding: 8px 12px;
                border-radius: 6px;
                min-height: 36px;
            }
            QPushButton#commandSendButton:hover, QPushButton#commandVoiceButton:hover, QPushButton#quickActionButton:hover {
                background-color: rgba(255, 176, 0, 0.16);
            }
            QPushButton#quickActionButton {
                text-align: left;
                font-weight: 600;
                letter-spacing: 1px;
                min-width: 0px;
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

        voice_detail = ""
        llm_detail = ""
        for key, label in self._status_detail_labels.items():
            detail = payload.get(key, {}).get("detail", "waiting for health check")
            label.setText(detail)
            if key == "voice":
                voice_detail = detail
            elif key == "llm":
                llm_detail = detail

        if voice_detail:
            self.voice_monitor_label.setText(voice_detail)
        if llm_detail or voice_detail:
            summary = " | ".join(part for part in (voice_detail, llm_detail) if part)
            self.runtime_label.setText(summary)

    def update_context(self, payload: dict) -> None:
        summary = payload.get("summary", "").strip() or "Waiting for active window data."
        self.context_summary_label.setText(summary)

        process_name = payload.get("process_name", "").strip()
        pid = payload.get("pid", 0)
        title = payload.get("title", "").strip()
        details = []
        if process_name:
            details.append(f"Process: {process_name}")
        if pid:
            details.append(f"PID: {pid}")
        if title:
            details.append(f"Window: {title}")
        details.append(f"Claude workspace: {self.settings.claude_code_workspace}")
        self.context_detail_label.setText(" | ".join(details))

    def prepare_to_quit(self) -> None:
        self._allow_close = True

    def show_and_focus(self) -> None:
        if self.isMinimized():
            self.showNormal()
        else:
            self.show()
        self.raise_()
        self.activateWindow()
        QTimer.singleShot(0, self.command_input.line_edit.setFocus)

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
