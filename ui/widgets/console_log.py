from __future__ import annotations

from PySide6.QtWidgets import QFrame, QPlainTextEdit, QVBoxLayout


class ConsoleLogWidget(QFrame):
    def __init__(self, max_blocks: int = 800, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("consoleFrame")

        self._view = QPlainTextEdit(self)
        self._view.setReadOnly(True)
        self._view.setMaximumBlockCount(max_blocks)
        self._view.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self._view.setObjectName("consoleView")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._view)

    def append_entry(self, payload: dict) -> None:
        timestamp = payload.get("timestamp", "--:--:--")
        role = str(payload.get("role", "system")).upper()[:3]
        text = str(payload.get("text", "")).strip()
        self._view.appendPlainText(f"[{timestamp}] {role} {text}")
        scrollbar = self._view.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
