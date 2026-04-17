from __future__ import annotations

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel


class StatusBadgesWidget(QFrame):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("statusBadgesFrame")
        self._labels: dict[str, QLabel] = {}

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        for key in ("llm", "voice", "memory", "actions"):
            label = QLabel(key.upper(), self)
            label.setObjectName("statusBadge")
            label.setProperty("state", "unknown")
            self._labels[key] = label
            layout.addWidget(label)

        layout.addStretch(1)

    def update_badges(self, statuses: dict[str, dict]) -> None:
        for key, label in self._labels.items():
            payload = statuses.get(key, {})
            state = payload.get("state", "unknown")
            detail = payload.get("detail", "")
            label.setText(f"{key.upper()} {state.upper()}")
            label.setToolTip(detail)
            label.setProperty("state", state)
            label.style().unpolish(label)
            label.style().polish(label)
