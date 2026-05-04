from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from smart_image_editor.core.histogram import HistogramStats


class HistogramWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumHeight(120)
        self.stats: HistogramStats | None = None

    def set_histogram(self, stats: HistogramStats | None) -> None:
        self.stats = stats
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#151729"))
        painter.setRenderHint(QPainter.Antialiasing, False)
        if not self.stats:
            painter.setPen(QColor("#8f93b3"))
            painter.drawText(self.rect(), Qt.AlignCenter, "Histogram")
            return

        channels = [
            (self.stats.red, QColor(255, 85, 110, 140)),
            (self.stats.green, QColor(105, 240, 213, 130)),
            (self.stats.blue, QColor(105, 150, 255, 130)),
            (self.stats.luminance, QColor(255, 255, 255, 150)),
        ]
        max_value = max(max(channel) for channel, _ in channels) or 1
        width = max(1, self.width())
        height = max(1, self.height())
        for channel, color in channels:
            painter.setPen(QPen(color, 1))
            last_x = 0
            last_y = height
            for idx, value in enumerate(channel):
                x = int(idx / 255 * (width - 1))
                y = height - int(value / max_value * (height - 10)) - 5
                painter.drawLine(last_x, last_y, x, y)
                last_x, last_y = x, y
