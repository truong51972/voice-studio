from __future__ import annotations

"""Preview overlay uses the same player clock as the bottom timeline."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import QWidget

from ...pipeline import AnalysisBundle
from ..theme import TRACK_COLORS

class DetectionOverlay(QWidget):
    """Paint current speaker matches directly over the media preview."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._bundle: AnalysisBundle | None = None
        self._position_seconds = 0.0
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

    def set_bundle(self, bundle: AnalysisBundle | None) -> None:
        self._bundle = bundle
        self.update()

    def set_position(self, seconds: float) -> None:
        self._position_seconds = max(0.0, seconds)
        self.update()

    def _active_results(self):
        if self._bundle is None:
            return []
        active = []
        for result in self._bundle.results:
            segment = next(
                (
                    segment
                    for segment in result.segments
                    if segment.start <= self._position_seconds <= segment.end
                ),
                None,
            )
            if segment is not None:
                active.append((result, segment))
        return active

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().paintEvent(event)
        active = self._active_results()
        if not active:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        margin = 18
        chip_height = 36
        gap = 8
        y = self.height() - margin - chip_height

        for index, (result, segment) in enumerate(reversed(active)):
            label = f"{result.name}  ·  {segment.max_score:.2f}"
            metrics = painter.fontMetrics()
            width = min(self.width() - 2 * margin, metrics.horizontalAdvance(label) + 34)
            x = margin
            color = TRACK_COLORS[(len(active) - index - 1) % len(TRACK_COLORS)]
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(10, 12, 16, 218))
            painter.drawRoundedRect(x, y, width, chip_height, 8, 8)
            painter.setBrush(color)
            painter.drawRoundedRect(x + 7, y + 7, 5, chip_height - 14, 2, 2)
            painter.setPen(QColor("#f5f7fa"))
            painter.drawText(
                x + 20,
                y,
                width - 26,
                chip_height,
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                label,
            )
            y -= chip_height + gap


class PreviewVideoWidget(QVideoWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.overlay = DetectionOverlay(self)
        self.overlay.setGeometry(self.rect())
        self.overlay.raise_()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        self.overlay.setGeometry(self.rect())
        self.overlay.raise_()
