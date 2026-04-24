from __future__ import annotations

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter
from PySide6.QtWidgets import QWidget


class ScanlineOverlay(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._phase = 0

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(75)

    def _tick(self) -> None:
        self._phase = (self._phase + 3) % max(120, self.height() + 120)
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

        for y in range(0, self.height(), 4):
            alpha = 10 if (y // 4) % 2 == 0 else 6
            painter.fillRect(0, y, self.width(), 1, QColor(132, 255, 205, alpha))

        sweep = QLinearGradient(0, self._phase - 120, 0, self._phase)
        sweep.setColorAt(0.0, QColor(132, 255, 205, 0))
        sweep.setColorAt(0.5, QColor(132, 255, 205, 14))
        sweep.setColorAt(1.0, QColor(132, 255, 205, 0))
        painter.fillRect(self.rect(), sweep)
