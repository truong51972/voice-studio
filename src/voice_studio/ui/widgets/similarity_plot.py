from __future__ import annotations

"""Qt-only similarity plot; no Plotly/web runtime."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ...config import DEFAULT_THRESHOLD
from ...pipeline import AnalysisBundle
from ..theme import TRACK_COLORS

class SimilarityPlotWidget(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._bundle: AnalysisBundle | None = None
        self._threshold = DEFAULT_THRESHOLD
        self.setMinimumHeight(160)

    def set_bundle(self, bundle: AnalysisBundle | None, threshold: float) -> None:
        self._bundle = bundle
        self._threshold = threshold
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#111318"))
        rect = self.rect().adjusted(38, 14, -12, -24)

        if self._bundle is None or not self._bundle.results:
            painter.setPen(QColor("#777f8b"))
            painter.drawText(
                self.rect(), Qt.AlignmentFlag.AlignCenter, "Similarity diagnostics"
            )
            return

        duration = max(self._bundle.duration, 0.001)
        painter.setPen(QPen(QColor("#353b44")))
        painter.drawRect(rect)

        threshold_y = rect.bottom() - int(rect.height() * self._threshold)
        threshold_pen = QPen(QColor("#8d96a3"))
        threshold_pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(threshold_pen)
        painter.drawLine(rect.left(), threshold_y, rect.right(), threshold_y)

        for index, result in enumerate(self._bundle.results):
            if not result.scores:
                continue
            pen = QPen(TRACK_COLORS[index % len(TRACK_COLORS)])
            pen.setWidth(2)
            painter.setPen(pen)
            previous = None
            for score in result.scores:
                center = (score.start + score.end) / 2.0
                x = rect.left() + int(rect.width() * center / duration)
                normalized = max(0.0, min(1.0, float(score.score)))
                y = rect.bottom() - int(rect.height() * normalized)
                if previous is not None:
                    painter.drawLine(previous[0], previous[1], x, y)
                previous = (x, y)
