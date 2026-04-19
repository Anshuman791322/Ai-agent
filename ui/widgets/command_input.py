from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLineEdit, QPushButton


class CommandInputWidget(QFrame):
    submitted = Signal(str)
    voice_requested = Signal()
    pause_requested = Signal()
    stop_requested = Signal()
    approve_requested = Signal()
    deny_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("commandInputFrame")

        self.line_edit = QLineEdit(self)
        self.line_edit.setObjectName("commandLineEdit")
        self.line_edit.setPlaceholderText("Type a command, try /search or /summarize, or say 'Jarvis' and then your command.")

        self.approve_button = QPushButton("APPROVE", self)
        self.approve_button.setObjectName("commandAuxButton")
        self.approve_button.setEnabled(False)

        self.deny_button = QPushButton("DENY", self)
        self.deny_button.setObjectName("commandAuxButton")
        self.deny_button.setEnabled(False)

        self.pause_button = QPushButton("PAUSE", self)
        self.pause_button.setObjectName("commandAuxButton")

        self.stop_button = QPushButton("STOP", self)
        self.stop_button.setObjectName("commandAuxButton")

        self.voice_button = QPushButton("PTT", self)
        self.voice_button.setObjectName("commandVoiceButton")
        self.voice_button.setToolTip("Fallback push-to-talk capture")

        self.send_button = QPushButton("SEND", self)
        self.send_button.setObjectName("commandSendButton")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(self.line_edit, 1)
        layout.addWidget(self.approve_button)
        layout.addWidget(self.deny_button)
        layout.addWidget(self.pause_button)
        layout.addWidget(self.stop_button)
        layout.addWidget(self.voice_button)
        layout.addWidget(self.send_button)

        self.line_edit.returnPressed.connect(self._emit_submit)
        self.send_button.clicked.connect(self._emit_submit)
        self.voice_button.clicked.connect(self.voice_requested.emit)
        self.pause_button.clicked.connect(self.pause_requested.emit)
        self.stop_button.clicked.connect(self.stop_requested.emit)
        self.approve_button.clicked.connect(self.approve_requested.emit)
        self.deny_button.clicked.connect(self.deny_requested.emit)

    def set_approval_buttons_enabled(self, enabled: bool) -> None:
        self.approve_button.setEnabled(enabled)
        self.deny_button.setEnabled(enabled)

    def _emit_submit(self) -> None:
        text = self.line_edit.text().strip()
        if not text:
            return
        self.submitted.emit(text)
        self.line_edit.clear()
