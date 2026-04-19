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

        for key in ("llm", "voice", "memory", "actions", "internet", "auto", "zone", "approvals"):
            label = QLabel(key.upper(), self)
            label.setObjectName("statusBadge")
            label.setProperty("state", "unknown")
            self._labels[key] = label
            layout.addWidget(label)

        layout.addStretch(1)

    def update_badges(self, statuses: dict[str, dict]) -> None:
        for key in ("llm", "voice", "memory", "actions", "internet"):
            label = self._labels[key]
            payload = statuses.get(key, {})
            state = payload.get("state", "unknown")
            detail = payload.get("detail", "")
            label.setText(f"{key.upper()} {state.upper()}")
            label.setToolTip(detail)
            label.setProperty("state", state)
            label.style().unpolish(label)
            label.style().polish(label)

    def update_policy_badges(self, payload: dict, approvals: dict | None = None) -> None:
        auto = self._labels["auto"]
        mode = str(payload.get("mode", "balanced")).replace("_", " ").upper()
        paused = bool(payload.get("autonomy_paused", False))
        auto.setText(f"AUTO {'PAUSED' if paused else mode}")
        auto.setToolTip("Autonomy mode")
        auto.setProperty("state", "warn" if paused else "ok")
        auto.style().unpolish(auto)
        auto.style().polish(auto)

        zone = self._labels["zone"]
        trust_zone = str(payload.get("trust_zone", "unknown")).replace("_", " ").upper()
        zone.setText(f"ZONE {trust_zone}")
        zone.setToolTip(str(payload.get("active_workspace", "")))
        zone_state = "ok" if "WORKSPACE" in trust_zone else ("warn" if "DOCUMENTS" in trust_zone else "error" if "FORBIDDEN" in trust_zone else "warn")
        zone.setProperty("state", zone_state)
        zone.style().unpolish(zone)
        zone.style().polish(zone)

        approvals_label = self._labels["approvals"]
        count = 0 if approvals is None else int(approvals.get("count", 0))
        approvals_label.setText(f"APPROVALS {count}")
        approvals_label.setToolTip("Pending high-risk approvals")
        approvals_label.setProperty("state", "warn" if count else "ok")
        approvals_label.style().unpolish(approvals_label)
        approvals_label.style().polish(approvals_label)
