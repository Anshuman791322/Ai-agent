from __future__ import annotations

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QCloseEvent, QFont, QFontInfo
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from config.settings import AppSettings
from ui.widgets.command_center import (
    CommandCenterBackdrop,
    MetricCard,
    QuickActionsPanel,
    TelemetryPanel,
)
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
    startup_toggle_requested = Signal()
    gemini_key_save_requested = Signal(str)
    gemini_key_clear_requested = Signal()

    def __init__(self, settings: AppSettings, parent=None) -> None:
        super().__init__(parent)
        self.settings = settings
        self._hide_to_tray = True
        self._allow_close = False
        self._status_detail_labels: dict[str, QLabel] = {}
        self._approvals_payload: dict = {"count": 0, "items": [], "first": {}}
        self._latest_statuses: dict[str, dict] = {}

        self.setWindowTitle(self.settings.window_title)
        screen = QApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            width = min(1680, max(1180, available.width() - 40))
            height = min(940, max(760, available.height() - 52))
            width = min(width, max(1040, available.width() - 10))
            height = min(height, max(700, available.height() - 10))
            self.resize(width, height)
        else:
            self.resize(1400, 860)
        self.setMinimumSize(1120, 740)

        self.setFont(self._choose_ui_font())

        central = CommandCenterBackdrop(self)
        central.setObjectName("mainWindowRoot")
        self.setCentralWidget(central)

        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(18, 18, 18, 18)
        root_layout.setSpacing(14)

        top_row = QHBoxLayout()
        top_row.setSpacing(14)
        top_row.addWidget(self._build_header(central), 7)
        top_row.addWidget(self._build_metric_strip(central), 6)
        root_layout.addLayout(top_row)

        self.status_badges = StatusBadgesWidget(central)
        root_layout.addWidget(self.status_badges)

        self.console_log = ConsoleLogWidget(max_blocks=self.settings.max_console_blocks, parent=central)
        self.console_log.setMinimumWidth(360)

        self.telemetry_panel = TelemetryPanel(central)
        self.telemetry_panel.setMinimumWidth(360)

        right_container = QWidget(central)
        right_container.setObjectName("rightColumnContainer")
        right_column = QVBoxLayout(right_container)
        right_column.setSpacing(14)
        right_column.setContentsMargins(0, 0, 12, 0)
        right_column.addWidget(self._build_context_panel(central))
        right_column.addWidget(self._build_status_panel(central))
        right_column.addWidget(self._build_gemini_key_panel(central))
        right_column.addWidget(self._build_internet_panel(central))
        right_column.addWidget(self._build_security_panel(central))
        right_column.addWidget(self._build_background_panel(central))
        right_column.addWidget(self._build_routines_panel(central))
        right_column.addWidget(self._build_voice_panel(central))
        right_column.addWidget(self._build_quick_actions_panel(central))
        right_column.addStretch(1)

        right_scroll = QScrollArea(central)
        right_scroll.setObjectName("rightScrollArea")
        right_scroll.setWidgetResizable(True)
        right_scroll.setFrameShape(QFrame.Shape.NoFrame)
        right_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        right_scroll.setWidget(right_container)
        right_scroll.setMinimumWidth(460)

        self.content_splitter = QSplitter(Qt.Orientation.Horizontal, central)
        self.content_splitter.setObjectName("contentSplitter")
        self.content_splitter.setChildrenCollapsible(False)
        self.content_splitter.setHandleWidth(12)
        self.content_splitter.addWidget(self.console_log)
        self.content_splitter.addWidget(self.telemetry_panel)
        self.content_splitter.addWidget(right_scroll)
        self.content_splitter.setStretchFactor(0, 10)
        self.content_splitter.setStretchFactor(1, 10)
        self.content_splitter.setStretchFactor(2, 10)
        self.content_splitter.setSizes([470, 410, 610])

        root_layout.addWidget(self.content_splitter, 1)

        self.command_input = CommandInputWidget(central)
        root_layout.addWidget(self.command_input)

        self.scanline_overlay = ScanlineOverlay(central)
        self.scanline_overlay.raise_()

        self._wire_controls()
        self._apply_styles()

    def _choose_ui_font(self) -> QFont:
        for family in ("Cascadia Mono", "Consolas", "Lucida Console", "Courier New"):
            font = QFont(family)
            font.setStyleHint(QFont.StyleHint.Monospace)
            if QFontInfo(font).family().lower() == family.lower():
                return font
        fallback = QFont()
        fallback.setStyleHint(QFont.StyleHint.Monospace)
        return fallback

    def _configure_panel_layout(self, layout: QVBoxLayout, *, spacing: int = 10) -> None:
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(spacing)

    def _panel_text(self, text: str) -> str:
        cleaned = str(text).strip()
        return (
            cleaned.replace(" | ", " |\n")
            .replace(" // ", " //\n")
            .replace("\\", "\\\u200b")
            .replace("/", "/\u200b")
        )

    def _build_header(self, parent: QWidget) -> QFrame:
        frame = QFrame(parent)
        frame.setObjectName("heroFrame")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)

        self.title_label = QLabel("JARVIS // WINDOWS COMMAND CENTER", frame)
        self.title_label.setObjectName("heroTitleLabel")
        self.subtitle_label = QLabel(
            f"WINDOWS-FIRST // ALWAYS-LISTENING // {self.settings.gemini_model.upper()} // {self.settings.whisper_model_size.upper()}",
            frame,
        )
        self.subtitle_label.setObjectName("heroSubtitleLabel")
        self.runtime_label = QLabel("Local systems are initializing.", frame)
        self.runtime_label.setObjectName("runtimeLabel")

        mode_row = QHBoxLayout()
        mode_row.setSpacing(12)
        mode_label = QLabel("Autonomy mode", frame)
        mode_label.setObjectName("inlineLabel")
        self.mode_selector = QComboBox(frame)
        self.mode_selector.setObjectName("modeSelector")
        self.mode_selector.addItem("Hands free", "hands_free")
        self.mode_selector.addItem("Balanced", "balanced")
        self.mode_selector.addItem("Strict", "strict")
        self.mode_selector.setCurrentIndex(1)
        self.mode_summary_label = QLabel("Workspace-safe medium risk stays autonomous.", frame)
        self.mode_summary_label.setObjectName("inlineHintLabel")
        self.mode_summary_label.setWordWrap(True)
        mode_row.addWidget(mode_label)
        mode_row.addWidget(self.mode_selector, 0)
        mode_row.addStretch(1)

        layout.addWidget(self.title_label)
        layout.addWidget(self.subtitle_label)
        layout.addWidget(self.runtime_label)
        layout.addLayout(mode_row)
        layout.addWidget(self.mode_summary_label)
        return frame

    def _build_metric_strip(self, parent: QWidget) -> QFrame:
        frame = QFrame(parent)
        frame.setObjectName("metricStripFrame")
        grid = QGridLayout(frame)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)
        self.metric_cards = {
            "llm": MetricCard("LLM", frame),
            "voice": MetricCard("Voice", frame),
            "memory": MetricCard("Memory", frame),
            "actions": MetricCard("Actions", frame),
        }
        for index, key in enumerate(("llm", "voice", "memory", "actions")):
            grid.addWidget(self.metric_cards[key], index // 2, index % 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        return frame

    def _build_context_panel(self, parent: QWidget) -> QFrame:
        frame = QFrame(parent)
        frame.setObjectName("panelFrame")
        layout = QVBoxLayout(frame)
        self._configure_panel_layout(layout)

        title = QLabel("Desktop context", frame)
        title.setObjectName("panelTitleLabel")
        subtitle = QLabel("Scoped visibility", frame)
        subtitle.setObjectName("panelSubTitleLabel")
        self.context_summary_label = QLabel("Waiting for active window data.", frame)
        self.context_summary_label.setObjectName("panelBodyLabel")
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
        frame.setObjectName("panelFrame")
        layout = QVBoxLayout(frame)
        self._configure_panel_layout(layout)

        title = QLabel("Subsystem digest", frame)
        title.setObjectName("panelTitleLabel")
        subtitle = QLabel("Live details from the current runtime", frame)
        subtitle.setObjectName("panelSubTitleLabel")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(10)
        for row, key in enumerate(("llm", "voice", "memory", "actions", "internet", "routines")):
            name_label = QLabel(key.upper(), frame)
            name_label.setObjectName("infoKeyLabel")
            detail_label = QLabel("waiting for health check", frame)
            detail_label.setObjectName("infoValueLabel")
            detail_label.setWordWrap(True)
            self._status_detail_labels[key] = detail_label
            grid.addWidget(name_label, row, 0)
            grid.addWidget(detail_label, row, 1)
        layout.addLayout(grid)
        return frame

    def _build_gemini_key_panel(self, parent: QWidget) -> QFrame:
        frame = QFrame(parent)
        frame.setObjectName("panelFrame")
        layout = QVBoxLayout(frame)
        self._configure_panel_layout(layout)

        title = QLabel("Gemini access", frame)
        title.setObjectName("panelTitleLabel")
        subtitle = QLabel("Backend-only key storage", frame)
        subtitle.setObjectName("panelSubTitleLabel")
        self.gemini_key_state_label = QLabel("Key state: checking secure storage", frame)
        self.gemini_key_state_label.setObjectName("panelBodyLabel")
        self.gemini_key_state_label.setWordWrap(True)
        helper = QLabel(
            "Paste a Gemini key here to save it in Windows Credential Manager. The field is hidden and never logged.",
            frame,
        )
        helper.setObjectName("panelBodyMuted")
        helper.setWordWrap(True)
        self.gemini_key_input = QLineEdit(frame)
        self.gemini_key_input.setObjectName("secretLineEdit")
        self.gemini_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.gemini_key_input.setPlaceholderText("Paste Gemini API key")
        self.gemini_key_input.setMaxLength(256)
        self.gemini_key_input.setClearButtonEnabled(True)

        button_row = QHBoxLayout()
        button_row.setSpacing(8)
        self.gemini_key_save_button = QPushButton("SAVE KEY", frame)
        self.gemini_key_save_button.setObjectName("quickActionButton")
        self.gemini_key_clear_button = QPushButton("CLEAR KEY", frame)
        self.gemini_key_clear_button.setObjectName("quickActionButton")
        button_row.addWidget(self.gemini_key_save_button)
        button_row.addWidget(self.gemini_key_clear_button)
        button_row.addStretch(1)

        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(self.gemini_key_state_label)
        layout.addWidget(helper)
        layout.addWidget(self.gemini_key_input)
        layout.addLayout(button_row)
        return frame

    def _build_internet_panel(self, parent: QWidget) -> QFrame:
        frame = QFrame(parent)
        frame.setObjectName("panelFrame")
        layout = QVBoxLayout(frame)
        self._configure_panel_layout(layout)

        title = QLabel("Internet tools", frame)
        title.setObjectName("panelTitleLabel")
        subtitle = QLabel("Constrained search and summaries", frame)
        subtitle.setObjectName("panelSubTitleLabel")
        self.internet_detail_label = QLabel("Search, fetch, and summarize stay capped until you use them.", frame)
        self.internet_detail_label.setObjectName("panelBodyLabel")
        self.internet_detail_label.setWordWrap(True)
        self.internet_examples_label = QLabel(
            "Commands: /search <query>, /open-result <n>, /fetch <url-or-n>, /summarize <url-or-n>",
            frame,
        )
        self.internet_examples_label.setObjectName("panelBodyMuted")
        self.internet_examples_label.setWordWrap(True)

        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(self.internet_detail_label)
        layout.addWidget(self.internet_examples_label)
        return frame

    def _build_security_panel(self, parent: QWidget) -> QFrame:
        frame = QFrame(parent)
        frame.setObjectName("panelFrame")
        layout = QVBoxLayout(frame)
        self._configure_panel_layout(layout, spacing=12)

        title = QLabel("Policy controls", frame)
        title.setObjectName("panelTitleLabel")
        subtitle = QLabel("Bounded autonomy and approvals", frame)
        subtitle.setObjectName("panelSubTitleLabel")
        self.approval_summary_label = QLabel("Pending approvals: 0", frame)
        self.approval_summary_label.setObjectName("panelBodyLabel")
        self.approval_summary_label.setWordWrap(True)
        self.active_task_label = QLabel("Active task: idle", frame)
        self.active_task_label.setObjectName("panelBodyMuted")

        self.pause_button = QPushButton("PAUSE", frame)
        self.pause_button.setObjectName("quickActionButton")
        self.deny_high_button = QPushButton("DENY HIGH", frame)
        self.deny_high_button.setObjectName("quickActionButton")
        self.clear_approvals_button = QPushButton("CLEAR QUEUE", frame)
        self.clear_approvals_button.setObjectName("quickActionButton")
        self.voice_toggle_button = QPushButton("VOICE", frame)
        self.voice_toggle_button.setObjectName("quickActionButton")
        self.approve_button = QPushButton("APPROVE NEXT", frame)
        self.approve_button.setObjectName("quickActionButton")
        self.approve_button.setEnabled(False)
        self.deny_button = QPushButton("DENY NEXT", frame)
        self.deny_button.setObjectName("quickActionButton")
        self.deny_button.setEnabled(False)

        controls_grid = QGridLayout()
        controls_grid.setHorizontalSpacing(8)
        controls_grid.setVerticalSpacing(8)
        controls_grid.setColumnStretch(0, 1)
        controls_grid.setColumnStretch(1, 1)
        controls_grid.addWidget(self.pause_button, 0, 0)
        controls_grid.addWidget(self.deny_high_button, 0, 1)
        controls_grid.addWidget(self.clear_approvals_button, 1, 0)
        controls_grid.addWidget(self.voice_toggle_button, 1, 1)
        controls_grid.addWidget(self.approve_button, 2, 0)
        controls_grid.addWidget(self.deny_button, 2, 1)

        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(self.approval_summary_label)
        layout.addWidget(self.active_task_label)
        layout.addLayout(controls_grid)
        return frame

    def _build_background_panel(self, parent: QWidget) -> QFrame:
        frame = QFrame(parent)
        frame.setObjectName("panelFrame")
        layout = QVBoxLayout(frame)
        self._configure_panel_layout(layout)

        title = QLabel("Background assistant", frame)
        title.setObjectName("panelTitleLabel")
        subtitle = QLabel("Tray and login behavior", frame)
        subtitle.setObjectName("panelSubTitleLabel")
        self.background_detail_label = QLabel(
            "Closing the window keeps JARVIS alive in the tray when the tray is available.",
            frame,
        )
        self.background_detail_label.setObjectName("panelBodyLabel")
        self.background_detail_label.setWordWrap(True)
        self.background_startup_label = QLabel("Startup on login: off", frame)
        self.background_startup_label.setObjectName("panelBodyMuted")
        self.background_toast_label = QLabel(
            "Windows notifications announce task completion and degraded health while JARVIS runs in the tray.",
            frame,
        )
        self.background_toast_label.setObjectName("panelBodyMuted")
        self.background_toast_label.setWordWrap(True)
        self.startup_toggle_button = QPushButton("ENABLE STARTUP", frame)
        self.startup_toggle_button.setObjectName("quickActionButton")

        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(self.background_detail_label)
        layout.addWidget(self.background_startup_label)
        layout.addWidget(self.background_toast_label)
        layout.addWidget(self.startup_toggle_button, 0, Qt.AlignmentFlag.AlignLeft)
        return frame

    def _build_routines_panel(self, parent: QWidget) -> QFrame:
        frame = QFrame(parent)
        frame.setObjectName("panelFrame")
        layout = QVBoxLayout(frame)
        self._configure_panel_layout(layout)

        title = QLabel("Routines", frame)
        title.setObjectName("panelTitleLabel")
        subtitle = QLabel("Local preset flows through the policy gate", frame)
        subtitle.setObjectName("panelSubTitleLabel")
        self.routines_summary_label = QLabel("Loading local routine catalog.", frame)
        self.routines_summary_label.setObjectName("panelBodyLabel")
        self.routines_summary_label.setWordWrap(True)
        self.routines_status_label = QLabel("No routine has run yet.", frame)
        self.routines_status_label.setObjectName("panelBodyMuted")
        self.routines_status_label.setWordWrap(True)
        self.routines_recent_label = QLabel("Starter routines will appear here.", frame)
        self.routines_recent_label.setObjectName("panelBodyMuted")
        self.routines_recent_label.setWordWrap(True)

        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(self.routines_summary_label)
        layout.addWidget(self.routines_status_label)
        layout.addWidget(self.routines_recent_label)
        return frame

    def _build_voice_panel(self, parent: QWidget) -> QFrame:
        frame = QFrame(parent)
        frame.setObjectName("panelFrame")
        layout = QVBoxLayout(frame)
        self._configure_panel_layout(layout)

        title = QLabel("Voice monitor", frame)
        title.setObjectName("panelTitleLabel")
        subtitle = QLabel("Wake phrase: Jarvis", frame)
        subtitle.setObjectName("panelSubTitleLabel")
        self.voice_monitor_label = QLabel(
            "Always-listening mode is enabled. Say 'Jarvis', pause if you want, then speak your command. The PTT button is only a fallback.",
            frame,
        )
        self.voice_monitor_label.setObjectName("panelBodyLabel")
        self.voice_monitor_label.setWordWrap(True)

        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(self.voice_monitor_label)
        return frame

    def _build_quick_actions_panel(self, parent: QWidget) -> QFrame:
        commands = (
            ("WORK MODE", "/run-routine Work Mode"),
            ("STREAM MODE", "/run-routine Stream Mode"),
            ("GAMING MODE", "/run-routine Gaming Mode"),
            ("CLAUDE CODE", "open claude code"),
            ("FILE EXPLORER", "open file explorer"),
            ("HEALTH CHECK", "/health"),
            ("ROUTINES", "/routines"),
            ("WEB SEARCH", "/search qt system tray icon"),
            ("LIST FILES", "/list"),
            ("RUN PYTEST", "/run pytest"),
        )
        panel = QuickActionsPanel(commands, parent)
        panel.command_requested.connect(self.quick_command_requested.emit)
        return panel

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
        self.startup_toggle_button.clicked.connect(self.startup_toggle_requested.emit)
        self.approve_button.clicked.connect(self.approve_requested.emit)
        self.deny_button.clicked.connect(self.deny_requested.emit)
        self.gemini_key_save_button.clicked.connect(self._save_gemini_key_from_ui)
        self.gemini_key_clear_button.clicked.connect(self.gemini_key_clear_requested.emit)

    def _save_gemini_key_from_ui(self) -> None:
        key = self.gemini_key_input.text().strip()
        self.gemini_key_input.clear()
        self.gemini_key_save_requested.emit(key)

    def _emit_mode_change(self) -> None:
        self.autonomy_mode_changed.emit(str(self.mode_selector.currentData()))

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QWidget#mainWindowRoot {
                background-color: transparent;
                color: #dcfff4;
            }
            QFrame#heroFrame, QFrame#panelFrame, QFrame#consoleFrame, QFrame#metricCard {
                border: 1px solid rgba(144, 255, 205, 0.20);
                border-radius: 18px;
                background-color: rgba(8, 18, 22, 0.84);
            }
            QFrame#metricStripFrame {
                background: transparent;
                border: none;
            }
            QSplitter#contentSplitter::handle {
                background: transparent;
            }
            QSplitter#contentSplitter::handle:horizontal {
                width: 12px;
            }
            QScrollArea#rightScrollArea {
                background: transparent;
                border: none;
            }
            QWidget#qt_scrollarea_viewport, QWidget#rightColumnContainer {
                background: transparent;
            }
            QScrollBar:vertical {
                background: rgba(7, 15, 18, 0.42);
                width: 10px;
                margin: 6px 0 6px 0;
                border-radius: 5px;
            }
            QScrollBar::handle:vertical {
                background: rgba(120, 255, 190, 0.34);
                border-radius: 5px;
                min-height: 38px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: transparent;
            }
            QLabel#heroTitleLabel {
                color: #c9fff4;
                font-size: 26px;
                font-weight: 700;
                letter-spacing: 2px;
            }
            QLabel#heroSubtitleLabel {
                color: rgba(178, 240, 223, 0.72);
                font-size: 10px;
                letter-spacing: 2px;
            }
            QLabel#runtimeLabel {
                color: #9ef5b8;
                font-size: 13px;
            }
            QLabel#inlineLabel {
                color: #d7fff3;
                font-size: 11px;
                letter-spacing: 1px;
            }
            QLabel#inlineHintLabel {
                color: rgba(219, 255, 244, 0.76);
                font-size: 11px;
            }
            QComboBox#modeSelector {
                background-color: rgba(7, 15, 18, 0.92);
                border: 1px solid rgba(144, 255, 205, 0.24);
                color: #f2fff9;
                padding: 8px 12px;
                border-radius: 10px;
                min-width: 210px;
            }
            QLineEdit#secretLineEdit {
                background-color: rgba(8, 15, 18, 0.92);
                border: 1px solid rgba(144, 255, 205, 0.24);
                color: #e8fff8;
                padding: 10px 12px;
                border-radius: 10px;
                font-size: 12px;
            }
            QLineEdit#secretLineEdit:focus {
                border: 1px solid rgba(140, 247, 176, 0.72);
            }
            QLabel#metricCardTitle {
                color: rgba(212, 255, 245, 0.72);
                font-size: 11px;
                letter-spacing: 1px;
            }
            QLabel#metricCardValue {
                color: #8cf7b0;
                font-size: 20px;
                font-weight: 700;
            }
            QLabel#metricCardDetail {
                color: rgba(211, 246, 234, 0.72);
                font-size: 10px;
            }
            QFrame#metricCard[state="warn"] QLabel#metricCardValue {
                color: #ffe382;
            }
            QFrame#metricCard[state="error"] QLabel#metricCardValue {
                color: #ff98a6;
            }
            QFrame#metricCard[state="busy"] QLabel#metricCardValue {
                color: #90f1ff;
            }
            QLabel#panelTitleLabel {
                color: #f2fff9;
                font-size: 14px;
                font-weight: 600;
            }
            QLabel#panelSubTitleLabel {
                color: rgba(138, 255, 210, 0.72);
                font-size: 11px;
            }
            QLabel#panelBodyLabel, QLabel#infoValueLabel {
                color: rgba(226, 245, 237, 0.88);
                font-size: 11px;
                line-height: 1.35em;
            }
            QLabel#panelBodyMuted {
                color: rgba(210, 238, 228, 0.68);
                font-size: 11px;
                line-height: 1.3em;
            }
            QLabel#infoKeyLabel {
                color: rgba(138, 255, 210, 0.78);
                font-size: 11px;
                letter-spacing: 1px;
            }
            QPlainTextEdit#consoleView {
                background-color: rgba(5, 10, 14, 0.92);
                color: #f0c97b;
                border: none;
                padding: 14px;
                selection-background-color: rgba(120, 255, 198, 0.18);
                font-size: 13px;
            }
            QFrame#commandInputFrame {
                border: 1px solid rgba(144, 255, 205, 0.20);
                border-radius: 18px;
                background-color: rgba(10, 18, 21, 0.88);
                padding: 8px;
            }
            QLineEdit#commandLineEdit {
                background-color: rgba(8, 15, 18, 0.92);
                border: 1px solid rgba(144, 255, 205, 0.24);
                color: #e8fff8;
                padding: 0 16px;
                border-radius: 10px;
                font-size: 13px;
                min-height: 42px;
            }
            QPushButton#commandSendButton, QPushButton#commandVoiceButton, QPushButton#commandAuxButton {
                background-color: rgba(120, 255, 190, 0.08);
                border: 1px solid rgba(135, 255, 196, 0.26);
                color: #dcfff4;
                padding: 0 14px;
                border-radius: 12px;
                min-height: 42px;
            }
            QPushButton#commandAuxButton {
                min-width: 86px;
            }
            QPushButton#commandVoiceButton {
                min-width: 64px;
            }
            QPushButton#commandSendButton {
                min-width: 92px;
            }
            QPushButton#commandSendButton {
                background-color: rgba(120, 255, 190, 0.18);
                color: #ffffff;
            }
            QPushButton#quickActionButton {
                background-color: rgba(120, 255, 190, 0.08);
                border: 1px solid rgba(135, 255, 196, 0.26);
                color: #dcfff4;
                padding: 8px 10px;
                border-radius: 12px;
                min-height: 38px;
                min-width: 0;
                font-weight: 600;
                letter-spacing: 0.8px;
            }
            QPushButton#commandSendButton:hover, QPushButton#commandVoiceButton:hover, QPushButton#commandAuxButton:hover, QPushButton#quickActionButton:hover {
                background-color: rgba(120, 255, 190, 0.18);
                border: 1px solid rgba(135, 255, 196, 0.42);
            }
            QPushButton:disabled {
                color: rgba(220, 255, 244, 0.34);
                border-color: rgba(135, 255, 196, 0.12);
            }
            QFrame#statusBadgesFrame {
                background: transparent;
            }
            QLabel#statusBadge {
                border-radius: 11px;
                padding: 7px 12px;
                font-size: 11px;
                letter-spacing: 1px;
                border: 1px solid rgba(140, 255, 190, 0.22);
                background-color: rgba(120, 255, 190, 0.06);
                color: #d6ffef;
            }
            QLabel#statusBadge[state="ok"] {
                border: 1px solid rgba(89, 255, 149, 0.3);
                background-color: rgba(89, 255, 149, 0.08);
                color: #8cffb1;
            }
            QLabel#statusBadge[state="warn"] {
                border: 1px solid rgba(255, 219, 109, 0.34);
                background-color: rgba(255, 219, 109, 0.12);
                color: #ffe68e;
            }
            QLabel#statusBadge[state="error"] {
                border: 1px solid rgba(255, 110, 130, 0.34);
                background-color: rgba(255, 110, 130, 0.10);
                color: #ff98a6;
            }
            QLabel#statusBadge[state="busy"] {
                border: 1px solid rgba(77, 214, 255, 0.35);
                background-color: rgba(77, 214, 255, 0.10);
                color: #88e7ff;
            }
            """
        )

    def set_hide_to_tray(self, enabled: bool) -> None:
        self._hide_to_tray = enabled

    def append_log(self, payload: dict) -> None:
        self.console_log.append_entry(payload)

    def update_statuses(self, payload: dict) -> None:
        self._latest_statuses = payload
        self.status_badges.update_badges(payload)
        self.telemetry_panel.update_statuses(payload)

        voice_detail = ""
        llm_detail = ""
        internet_detail = ""
        internet_state = ""
        routine_detail = ""
        routine_state = ""
        for key, label in self._status_detail_labels.items():
            detail = payload.get(key, {}).get("detail", "waiting for health check")
            label.setText(self._panel_text(detail))
            if key == "voice":
                voice_detail = detail
            elif key == "llm":
                llm_detail = detail
            elif key == "internet":
                internet_detail = detail
                internet_state = str(payload.get(key, {}).get("state", "unknown"))
            elif key == "routines":
                routine_detail = detail
                routine_state = str(payload.get(key, {}).get("state", "unknown"))

        for key, card in self.metric_cards.items():
            item = payload.get(key, {})
            state = str(item.get("state", "unknown"))
            detail = str(item.get("detail", "awaiting data"))
            value = {
                "ok": "OK",
                "warn": "WARN",
                "error": "FAIL",
                "busy": "LIVE",
            }.get(state, "--")
            card.set_metric(key.upper(), value, detail, state)

        if voice_detail:
            self.voice_monitor_label.setText(voice_detail)
        if internet_detail:
            self.internet_detail_label.setText(internet_detail)
        summary = " | ".join(
            part
            for part in (
                voice_detail,
                llm_detail,
                internet_detail if internet_state in {"warn", "error"} else "",
                routine_detail if routine_state in {"busy", "warn", "error"} else "",
            )
            if part
        )
        if summary:
            self.runtime_label.setText(summary)

    def update_context(self, payload: dict) -> None:
        summary = payload.get("summary", "").strip() or "Waiting for active window data."
        self.context_summary_label.setText(self._panel_text(summary))

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
        tray_available = bool(payload.get("tray_available", True))
        start_on_login = bool(payload.get("start_on_login_enabled", False))
        startup_detail = str(payload.get("start_on_login_detail", "startup on login is off"))

        self.mode_summary_label.setText(
            "Autonomy paused."
            if paused
            else "Workspace-safe medium risk stays autonomous."
            if mode == "balanced"
            else "Low and medium risk stay autonomous."
            if mode == "hands_free"
            else "Only low risk stays autonomous."
        )
        self.trust_zone_label.setText(self._panel_text(f"Trust zone: {trust_zone} | workspace: {workspace}"))
        self.context_usage_label.setText(self._panel_text(f"Context in use: {context_usage}"))
        self.memory_usage_label.setText(self._panel_text(f"Memory usage: {memory_used} items, {blocked} blocked"))
        self.handoff_label.setText(self._panel_text(f"Claude handoff: {handoff_state} | workspace: {workspace}"))
        self.active_task_label.setText(self._panel_text(f"Active task: {active_task}"))
        self.pause_button.setText("RESUME" if paused else "PAUSE")
        self.deny_high_button.setText("ALLOW HIGH" if deny_high else "DENY HIGH")
        self.background_detail_label.setText(
            "Tray quick actions: hide or show the window, capture voice, run a health check, open Claude Code, pause, stop, or quit."
            if tray_available
            else "System tray is unavailable. Closing the window exits the app instead of keeping it in the background."
        )
        self.background_startup_label.setText(
            self._panel_text(f"Startup on login: {'on' if start_on_login else 'off'} | {startup_detail}")
        )
        self.startup_toggle_button.setText("DISABLE STARTUP" if start_on_login else "ENABLE STARTUP")
        self.status_badges.update_policy_badges(payload, self._approvals_payload)

    def update_gemini_key_state(self, payload: dict) -> None:
        has_key = bool(payload.get("has_key", False))
        source = str(payload.get("source", "missing"))
        detail = str(payload.get("detail", "Gemini key state unavailable"))
        prefix = "stored" if has_key else "missing"
        self.gemini_key_state_label.setText(self._panel_text(f"Key state: {prefix} | source: {source} | {detail}"))

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

    def update_routines(self, payload: dict) -> None:
        available = payload.get("available", []) or []
        recent_runs = payload.get("recent_runs", []) or []
        active_routine = str(payload.get("active_routine", "")).strip()
        status_text = str(payload.get("status", "")).strip()

        if available:
            names = ", ".join(item.get("name", "routine") for item in available)
            self.routines_summary_label.setText(
                self._panel_text(f"Loaded {len(available)} routines | {names}")
            )
        else:
            self.routines_summary_label.setText("No local routines are stored.")

        if active_routine:
            self.routines_status_label.setText(self._panel_text(f"Active routine: {active_routine}"))
        elif status_text:
            self.routines_status_label.setText(self._panel_text(status_text))
        else:
            self.routines_status_label.setText("No routine has run yet.")

        if recent_runs:
            lines = []
            for item in recent_runs[:4]:
                lines.append(
                    f"{item.get('name', 'routine')} [{str(item.get('status', 'unknown')).upper()}] {item.get('finished_at', '')}"
                )
            self.routines_recent_label.setText("\n".join(lines))
        else:
            self.routines_recent_label.setText("Recent runs will appear here once a routine executes.")

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
