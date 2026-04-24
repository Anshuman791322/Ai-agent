from __future__ import annotations

import math
from collections import deque
from functools import partial

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget


def shorten(text: str, limit: int = 84) -> str:
    compact = " ".join(str(text).split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3].rstrip() + "..."


def state_color(state: str) -> QColor:
    return {
        "ok": QColor("#8cf7b0"),
        "warn": QColor("#ffd773"),
        "error": QColor("#ff8c99"),
        "busy": QColor("#85edff"),
        "unknown": QColor("#9fb7c1"),
    }.get(str(state).lower(), QColor("#9fb7c1"))


def state_score(state: str) -> float:
    return {
        "ok": 0.94,
        "busy": 0.76,
        "warn": 0.52,
        "error": 0.22,
        "unknown": 0.36,
    }.get(str(state).lower(), 0.36)


PANEL_CONTENT_MARGINS = (18, 16, 18, 16)
PANEL_CONTENT_SPACING = 10
CARD_CONTENT_MARGINS = (16, 14, 16, 14)


def apply_panel_spacing(
    layout,
    *,
    margins: tuple[int, int, int, int] = PANEL_CONTENT_MARGINS,
    spacing: int = PANEL_CONTENT_SPACING,
) -> None:
    layout.setContentsMargins(*margins)
    layout.setSpacing(spacing)


class CommandCenterBackdrop(QWidget):
    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        gradient = QLinearGradient(0, 0, self.width(), self.height())
        gradient.setColorAt(0.0, QColor("#09141b"))
        gradient.setColorAt(0.42, QColor("#0a1a21"))
        gradient.setColorAt(1.0, QColor("#081116"))
        painter.fillRect(self.rect(), gradient)

        painter.setPen(QPen(QColor(96, 255, 196, 18), 1))
        for x in range(0, self.width(), 84):
            painter.drawLine(x, 0, x, self.height())
        for y in range(0, self.height(), 76):
            painter.drawLine(0, y, self.width(), y)

        painter.setPen(QPen(QColor(85, 255, 190, 22), 2))
        path = QPainterPath()
        path.moveTo(0, int(self.height() * 0.58))
        path.lineTo(int(self.width() * 0.22), int(self.height() * 0.58))
        path.lineTo(int(self.width() * 0.29), int(self.height() * 0.49))
        path.lineTo(int(self.width() * 0.48), int(self.height() * 0.49))
        path.lineTo(int(self.width() * 0.55), int(self.height() * 0.35))
        path.lineTo(int(self.width() * 0.82), int(self.height() * 0.35))
        painter.drawPath(path)

        painter.setPen(QPen(QColor(72, 255, 188, 14), 3))
        path2 = QPainterPath()
        path2.moveTo(int(self.width() * 0.24), self.height())
        path2.lineTo(int(self.width() * 0.24), int(self.height() * 0.71))
        path2.lineTo(int(self.width() * 0.41), int(self.height() * 0.71))
        path2.lineTo(int(self.width() * 0.47), int(self.height() * 0.63))
        path2.lineTo(int(self.width() * 0.74), int(self.height() * 0.63))
        painter.drawPath(path2)

        for center_x, center_y, radius in (
            (int(self.width() * 0.12), int(self.height() * 0.33), 80),
            (int(self.width() * 0.72), int(self.height() * 0.17), 64),
            (int(self.width() * 0.76), int(self.height() * 0.66), 94),
        ):
            glow = QLinearGradient(center_x - radius, center_y - radius, center_x + radius, center_y + radius)
            glow.setColorAt(0.0, QColor(110, 255, 190, 0))
            glow.setColorAt(0.5, QColor(110, 255, 190, 18))
            glow.setColorAt(1.0, QColor(110, 255, 190, 0))
            painter.fillRect(center_x - radius, center_y - radius, radius * 2, radius * 2, glow)


class MetricCard(QFrame):
    def __init__(self, title: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("metricCard")
        self._state = "unknown"
        self.setMinimumHeight(112)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        layout = QVBoxLayout(self)
        apply_panel_spacing(layout, margins=CARD_CONTENT_MARGINS, spacing=6)

        self.title_label = QLabel(title, self)
        self.title_label.setObjectName("metricCardTitle")
        self.value_label = QLabel("--", self)
        self.value_label.setObjectName("metricCardValue")
        self.detail_label = QLabel("awaiting data", self)
        self.detail_label.setObjectName("metricCardDetail")
        self.detail_label.setWordWrap(True)

        layout.addWidget(self.title_label)
        layout.addWidget(self.value_label)
        layout.addWidget(self.detail_label)

    def set_metric(self, title: str, value: str, detail: str, state: str) -> None:
        self._state = state
        self.title_label.setText(title)
        self.value_label.setText(value)
        self.detail_label.setText(shorten(detail, 42))
        self.setProperty("state", state)
        self.style().unpolish(self)
        self.style().polish(self)


class TelemetryCanvas(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.statuses: dict[str, dict] = {}
        self.history: dict[str, deque[float]] = {
            key: deque(maxlen=36) for key in ("llm", "voice", "memory", "actions", "internet")
        }
        self.setMinimumHeight(280)

    def update_statuses(self, statuses: dict[str, dict]) -> None:
        self.statuses = statuses
        for key, history in self.history.items():
            state = statuses.get(key, {}).get("state", "unknown")
            history.append(state_score(state))
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self.rect().adjusted(8, 8, -8, -8)

        radar_rect = rect.adjusted(0, 0, 0, -int(rect.height() * 0.36))
        center = QPointF(radar_rect.center())
        radius = min(radar_rect.width(), radar_rect.height()) * 0.27
        labels = ("LLM", "VOICE", "MEMORY", "ACTIONS", "NET")
        keys = ("llm", "voice", "memory", "actions", "internet")

        painter.setPen(QPen(QColor(140, 255, 211, 34), 1))
        for ring in range(1, 5):
            painter.drawPolygon(self._regular_polygon(center, radius * ring / 4, len(labels)))

        for index, label in enumerate(labels):
            angle = -math.pi / 2 + (math.tau * index / len(labels))
            axis_point = QPointF(center.x() + math.cos(angle) * radius, center.y() + math.sin(angle) * radius)
            painter.drawLine(center, axis_point)
            text_point = QPointF(center.x() + math.cos(angle) * (radius + 26), center.y() + math.sin(angle) * (radius + 26))
            painter.setPen(QPen(QColor(219, 255, 243, 200), 1))
            painter.drawText(text_point.x() - 22, text_point.y() + 4, label)
            painter.setPen(QPen(QColor(140, 255, 211, 34), 1))

        polygon = QPolygonF()
        for index, key in enumerate(keys):
            angle = -math.pi / 2 + (math.tau * index / len(keys))
            score = self.history[key][-1] if self.history[key] else 0.35
            polygon.append(
                QPointF(
                    center.x() + math.cos(angle) * radius * score,
                    center.y() + math.sin(angle) * radius * score,
                )
            )
        painter.setPen(QPen(QColor("#7af8cb"), 2))
        painter.setBrush(QColor(122, 248, 203, 45))
        painter.drawPolygon(polygon)

        graph_rect = rect.adjusted(10, int(rect.height() * 0.65), -10, -8)
        painter.setPen(QPen(QColor(122, 255, 205, 24), 1))
        for step in range(5):
            y = graph_rect.top() + step * graph_rect.height() / 4
            painter.drawLine(graph_rect.left(), y, graph_rect.right(), y)

        self._draw_history_line(painter, graph_rect, list(self.history["voice"]), QColor("#89ffd0"), 0)
        self._draw_history_line(painter, graph_rect, list(self.history["memory"]), QColor("#ffd56e"), 3)
        self._draw_history_line(painter, graph_rect, list(self.history["internet"]), QColor("#7ee9ff"), 6)

    def _regular_polygon(self, center: QPointF, radius: float, count: int) -> QPolygonF:
        polygon = QPolygonF()
        for index in range(count):
            angle = -math.pi / 2 + (math.tau * index / count)
            polygon.append(QPointF(center.x() + math.cos(angle) * radius, center.y() + math.sin(angle) * radius))
        return polygon

    def _draw_history_line(self, painter: QPainter, rect, values: list[float], color: QColor, offset: int) -> None:
        if len(values) < 2:
            return
        painter.setPen(QPen(color, 2))
        path = QPainterPath()
        for index, value in enumerate(values):
            x = rect.left() + rect.width() * index / max(1, len(values) - 1)
            y = rect.bottom() - rect.height() * value * 0.9 - offset
            if index == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)
        painter.drawPath(path)


class TelemetryPanel(QFrame):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("panelFrame")

        layout = QVBoxLayout(self)
        apply_panel_spacing(layout)

        self.title_label = QLabel("Subsystem telemetry", self)
        self.title_label.setObjectName("panelTitleLabel")
        self.subtitle_label = QLabel("Radar snapshot with a short trend line", self)
        self.subtitle_label.setObjectName("panelSubTitleLabel")
        self.canvas = TelemetryCanvas(self)
        self.summary_label = QLabel("Waiting for subsystem data.", self)
        self.summary_label.setObjectName("panelBodyLabel")
        self.summary_label.setWordWrap(True)

        layout.addWidget(self.title_label)
        layout.addWidget(self.subtitle_label)
        layout.addWidget(self.canvas, 1)
        layout.addWidget(self.summary_label)

    def update_statuses(self, statuses: dict[str, dict]) -> None:
        self.canvas.update_statuses(statuses)
        parts = []
        for key in ("llm", "voice", "memory", "actions", "internet"):
            item = statuses.get(key, {})
            parts.append(f"{key.upper()} {str(item.get('state', 'unknown')).upper()} | {shorten(item.get('detail', ''), 30)}")
        self.summary_label.setText(" // ".join(parts))


class QuickActionsPanel(QFrame):
    command_requested = Signal(str)

    def __init__(self, commands: tuple[tuple[str, str], ...], parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("panelFrame")

        layout = QVBoxLayout(self)
        apply_panel_spacing(layout)

        self.title_label = QLabel("Quick actions", self)
        self.title_label.setObjectName("panelTitleLabel")
        self.subtitle_label = QLabel("Fast paths into common Jarvis commands", self)
        self.subtitle_label.setObjectName("panelSubTitleLabel")
        layout.addWidget(self.title_label)
        layout.addWidget(self.subtitle_label)

        grid = QGridLayout()
        grid.setContentsMargins(0, 2, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        for index, (label, command) in enumerate(commands):
            button = QPushButton(label, self)
            button.setObjectName("quickActionButton")
            button.setMinimumHeight(38)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            button.clicked.connect(partial(self.command_requested.emit, command))
            grid.addWidget(button, index // 2, index % 2)

        layout.addLayout(grid)


class InfoPanel(QFrame):
    def __init__(self, title: str, subtitle: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("panelFrame")

        layout = QVBoxLayout(self)
        apply_panel_spacing(layout)

        self.title_label = QLabel(title, self)
        self.title_label.setObjectName("panelTitleLabel")
        self.subtitle_label = QLabel(subtitle, self)
        self.subtitle_label.setObjectName("panelSubTitleLabel")
        self.body_label = QLabel("Waiting for data.", self)
        self.body_label.setObjectName("panelBodyLabel")
        self.body_label.setWordWrap(True)

        layout.addWidget(self.title_label)
        layout.addWidget(self.subtitle_label)
        layout.addWidget(self.body_label)

    def set_body(self, text: str) -> None:
        self.body_label.setText(text)
