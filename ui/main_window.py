from __future__ import annotations

from functools import partial

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QCloseEvent, QFont
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
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
    autonomy_mode_changed = Signal(str)
    pause_requested = Signal()
    deny_high_risk_requested = Signal()
    stop_requested = Signal()
    approve_requested = Signal()
    deny_requested = Signal()
    clear_approvals_requested = Signal()
    voice_toggle_requested = Signal()

    def __init__(self, settings: AppSettings, parent=None) -> None:
        super().__init__(parent)
        self.settings = settings
        self._hide_to_tray = True
        self._allow_close = False
        self._status_detail_labels: dict[str, QLabel] = {}
        self._approvals_payload: dict = {"count": 0, "items": [], "first": {}}

        self.setWindowTitle(self.settings.window_title)
        screen = QApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            width = max(1120, min(1380, available.width() - 48))
            height = max(720, min(860, available.height() - 72))
            self.resize(width, height)
        else:
            self.resize(1360, 840)
        self.setMinimumSize(1120, 720)

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
        right_column.addWidget(self._build_security_panel(central))
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

        self._wire_controls()
        self._apply_styles()

    def _build_header(self, parent: QWidget) -> QFrame:
        header = QFrame(parent)
        header.setObjectName("headerFrame")

        layout = QVBoxLayout(header)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        top_row = QHBoxLayout()
        top_row.setSpacing(12)

        title_block = QVBoxLayout()
        title_block.setSpacing(4)

        title = QLabel("JARVIS // WINDOWS COMMAND CENTER", header)
        title.setObjectName("titleLabel")
        subtitle = QLabel(
            f"LOCAL-FIRST // POLICY-BOUND // {self.settings.ollama_model.upper()} // {self.settings.whisper_model_size.upper()}",
            header,
        )
        subtitle.setObjectName("subtitleLabel")
        self.runtime_label = QLabel("Balanced autonomy online. Local systems are initializing.", header)
        self.runtime_label.setObjectName("runtimeLabel")

        title_block.addWidget(title)
        title_block.addWidget(subtitle)
        title_block.addWidget(self.runtime_label)

        mode_block = QVBoxLayout()
        mode_block.setSpacing(4)
        mode_label = QLabel("Autonomy mode", header)
        mode_label.setObjectName("panelAccent")
        self.mode_selector = QComboBox(header)
        self.mode_selector.setObjectName("modeSelector")
        self.mode_selector.addItem("Hands free", "hands_free")
        self.mode_selector.addItem("Balanced", "balanced")
        self.mode_selector.addItem("Strict", "strict")
        self.mode_selector.setCurrentIndex(1)
        self.mode_summary_label = QLabel("Allowed workspace actions stay autonomous.", header)
        self.mode_summary_label.setObjectName("panelBodyMuted")
        self.mode_summary_label.setWordWrap(True)
        mode_block.addWidget(mode_label)
        mode_block.addWidget(self.mode_selector)
        mode_block.addWidget(self.mode_summary_label)

        top_row.addLayout(title_block, 4)
        top_row.addLayout(mode_block, 2)
        layout.addLayout(top_row)
        return header

    def _build_context_panel(self, parent: QWidget) -> QFrame:
        frame = QFrame(parent)
        frame.setObjectName("infoPanel")

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        title = QLabel("Context and trust", frame)
        title.setObjectName("panelTitle")
        subtitle = QLabel("Scoped visibility", frame)
        subtitle.setObjectName("panelAccent")
        self.context_summary_label = QLabel("Waiting for active window data.", frame)
        self.context_summary_label.setObjectName("panelBody")
        self.context_summary_label.setWordWrap(True)
        self.trust_zone_label = QLabel("Trust zone: allowed_workspace", frame)
        self.trust_zone_label.setObjectName("panelBodyMuted")
        self.context_usage_label = QLabel("Context in use: recent_chat", frame)
        self.context_usage_label.setObjectName("panelBodyMuted")
        self.memory_usage_label = QLabel("Memory usage: 0 items, 0 blocked", frame)
        self.memory_usage_label.setObjectName("panelBodyMuted")
        self.handoff_label = QLabel(f"Claude handoff: idle | workspace: {self.settings.claude_code_workspace}", frame)
        self.handoff_label.setObjectName("panelBodyMuted")

        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(self.context_summary_label)
        layout.addWidget(self.trust_zone_label)
        layout.addWidget(self.context_usage_label)
        layout.addWidget(self.memory_usage_label)
        layout.addWidget(self.handoff_label)
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

    def _build_security_panel(self, parent: QWidget) -> QFrame:
        frame = QFrame(parent)
        frame.setObjectName("infoPanel")

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        title = QLabel("Policy controls", frame)
        title.setObjectName("panelTitle")
        self.approval_summary_label = QLabel("Pending approvals: 0", frame)
        self.approval_summary_label.setObjectName("panelBody")
        self.approval_summary_label.setWordWrap(True)
        self.active_task_label = QLabel("Active task: idle", frame)
        self.active_task_label.setObjectName("panelBodyMuted")

        button_row = QHBoxLayout()
        button_row.setSpacing(8)
        self.pause_button = QPushButton("PAUSE", frame)
        self.pause_button.setObjectName("quickActionButton")
        self.deny_high_button = QPushButton("DENY HIGH", frame)
        self.deny_high_button.setObjectName("quickActionButton")
        self.clear_approvals_button = QPushButton("CLEAR QUEUE", frame)
        self.clear_approvals_button.setObjectName("quickActionButton")
        self.voice_toggle_button = QPushButton("VOICE", frame)
        self.voice_toggle_button.setObjectName("quickActionButton")
        button_row.addWidget(self.pause_button)
        button_row.addWidget(self.deny_high_button)
        button_row.addWidget(self.clear_approvals_button)
        button_row.addWidget(self.voice_toggle_button)

        approval_row = QHBoxLayout()
        approval_row.setSpacing(8)
        self.approve_button = QPushButton("APPROVE NEXT", frame)
        self.approve_button.setObjectName("quickActionButton")
        self.approve_button.setEnabled(False)
        self.deny_button = QPushButton("DENY NEXT", frame)
        self.deny_button.setObjectName("quickActionButton")
        self.deny_button.setEnabled(False)
        approval_row.addWidget(self.approve_button)
        approval_row.addWidget(self.deny_button)

        layout.addWidget(title)
        layout.addWidget(self.approval_summary_label)
        layout.addWidget(self.active_task_label)
        layout.addLayout(button_row)
        layout.addLayout(approval_row)
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
            ("OPEN CHROME", "open google chrome"),
            ("HEALTH CHECK", "/health"),
            ("LIST FILES", "/list"),
            ("RUN TESTS", "/run pytest"),
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

    def _wire_controls(self) -> None:
        self.command_input.pause_requested.connect(self.pause_requested.emit)
        self.command_input.stop_requested.connect(self.stop_requested.emit)
        self.command_input.approve_requested.connect(self.approve_requested.emit)
        self.command_input.deny_requested.connect(self.deny_requested.emit)

        self.mode_selector.currentIndexChanged.connect(self._emit_mode_change)
        self.pause_button.clicked.connect(self.pause_requested.emit)
        self.deny_high_button.clicked.connect(self.deny_high_risk_requested.emit)
        self.clear_approvals_button.clicked.connect(self.clear_approvals_requested.emit)
        self.voice_toggle_button.clicked.connect(self.voice_toggle_requested.emit)
        self.approve_button.clicked.connect(self.approve_requested.emit)
        self.deny_button.clicked.connect(self.deny_requested.emit)

    def _emit_mode_change(self) -> None:
        self.autonomy_mode_changed.emit(str(self.mode_selector.currentData()))

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
            QComboBox#modeSelector {
                background-color: rgba(0, 0, 0, 0.88);
                border: 1px solid rgba(255, 176, 0, 0.25);
                color: #ffe1a3;
                padding: 8px;
                border-radius: 6px;
                min-width: 180px;
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
            QPushButton#commandSendButton, QPushButton#commandVoiceButton, QPushButton#commandAuxButton, QPushButton#quickActionButton {
                background-color: rgba(255, 176, 0, 0.08);
                border: 1px solid rgba(255, 176, 0, 0.32);
                color: #ffb000;
                padding: 8px 12px;
                border-radius: 6px;
                min-height: 36px;
            }
            QPushButton#commandSendButton:hover, QPushButton#commandVoiceButton:hover, QPushButton#commandAuxButton:hover, QPushButton#quickActionButton:hover {
                background-color: rgba(255, 176, 0, 0.16);
            }
            QPushButton#quickActionButton {
                text-align: left;
                font-weight: 600;
                letter-spacing: 1px;
                min-width: 0px;
            }
            QPushButton:disabled {
                color: rgba(255, 176, 0, 0.35);
                border-color: rgba(255, 176, 0, 0.12);
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

    def update_policy_state(self, payload: dict) -> None:
        mode = str(payload.get("mode", "balanced"))
        for index in range(self.mode_selector.count()):
            if self.mode_selector.itemData(index) == mode:
                self.mode_selector.blockSignals(True)
                self.mode_selector.setCurrentIndex(index)
                self.mode_selector.blockSignals(False)
                break

        paused = bool(payload.get("autonomy_paused", False))
        deny_high = bool(payload.get("deny_high_risk", False))
        trust_zone = str(payload.get("trust_zone", "unknown"))
        workspace = str(payload.get("active_workspace", ""))
        context_usage = str(payload.get("context_usage", "minimal"))
        handoff_state = str(payload.get("handoff_state", "idle"))
        active_task = str(payload.get("active_task", "idle"))
        memory_used = int(payload.get("memory_items_used", 0))
        blocked = int(payload.get("sensitive_items_blocked", 0))

        self.mode_summary_label.setText(
            "Autonomy paused." if paused else (
                "Workspace-safe medium risk runs automatically." if mode == "balanced" else
                "Low and medium risk run automatically." if mode == "hands_free" else
                "Only low risk runs automatically."
            )
        )
        self.trust_zone_label.setText(f"Trust zone: {trust_zone} | workspace: {workspace}")
        self.context_usage_label.setText(f"Context in use: {context_usage}")
        self.memory_usage_label.setText(f"Memory usage: {memory_used} items, {blocked} blocked")
        self.handoff_label.setText(f"Claude handoff: {handoff_state} | workspace: {workspace}")
        self.active_task_label.setText(f"Active task: {active_task}")
        self.pause_button.setText("RESUME" if paused else "PAUSE")
        self.deny_high_button.setText("ALLOW HIGH" if deny_high else "DENY HIGH")
        self.status_badges.update_policy_badges(payload, self._approvals_payload)

    def update_approval_state(self, payload: dict) -> None:
        self._approvals_payload = payload
        count = int(payload.get("count", 0))
        first = payload.get("first", {}) or {}
        if count:
            summary = first.get("summary", "approval pending")
            risk = first.get("risk", "high")
            self.approval_summary_label.setText(f"Pending approvals: {count} | next: {summary} [{risk}]")
        else:
            self.approval_summary_label.setText("Pending approvals: 0")
        enabled = count > 0
        self.approve_button.setEnabled(enabled)
        self.deny_button.setEnabled(enabled)
        self.command_input.set_approval_buttons_enabled(enabled)
        self.status_badges.update_policy_badges(
            {
                "mode": self.mode_selector.currentData(),
                "autonomy_paused": self.pause_button.text() == "RESUME",
                "trust_zone": self.trust_zone_label.text().split(":", 1)[-1].strip().split("|", 1)[0].strip(),
                "active_workspace": self.settings.claude_code_workspace,
            },
            payload,
        )

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
