from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLineEdit, QPushButton


class CommandInputWidget(QFrame):
    submitted = Signal(str)
    voice_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("commandInputFrame")

        self.line_edit = QLineEdit(self)
        self.line_edit.setObjectName("commandLineEdit")
        self.line_edit.setPlaceholderText("Type a command, ask a question, or use /help")

        self.send_button = QPushButton("SEND", self)
        self.send_button.setObjectName("commandSendButton")

        self.voice_button = QPushButton("VOICE", self)
        self.voice_button.setObjectName("commandVoiceButton")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(self.line_edit, 1)
        layout.addWidget(self.voice_button)
        layout.addWidget(self.send_button)

        self.line_edit.returnPressed.connect(self._emit_submit)
        self.send_button.clicked.connect(self._emit_submit)
        self.voice_button.clicked.connect(self.voice_requested.emit)

    def _emit_submit(self) -> None:
        text = self.line_edit.text().strip()
        if not text:
            return
        self.submitted.emit(text)
        self.line_edit.clear()
