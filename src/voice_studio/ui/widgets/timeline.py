from __future__ import annotations

"""Speaker tracks over a source-local seconds timebase."""

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPolygon
from PySide6.QtWidgets import QWidget

from ...pipeline import AnalysisBundle
from ..theme import TRACK_COLORS
from ..timecode import _fmt_time

class EditorTimelineWidget(QWidget):
    """Video-editor style speaker tracks with ruler, clips and a synced playhead."""

    seekRequested = Signal(float)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._bundle: AnalysisBundle | None = None
        self._duration = 0.0
        self._position_seconds = 0.0
        self.setMinimumHeight(205)

    def set_bundle(self, bundle: AnalysisBundle | None) -> None:
        self._bundle = bundle
        if bundle is not None:
            self._duration = max(self._duration, bundle.duration)
        self.update()

    def set_duration_seconds(self, duration: float) -> None:
        self._duration = max(0.0, float(duration))
        self.update()

    def set_position_seconds(self, seconds: float) -> None:
        self._position_seconds = max(0.0, float(seconds))
        self.update()

    def _track_rect(self):
        return self.rect().adjusted(112, 30, -16, -16)

    def _duration_seconds(self) -> float:
        if self._bundle is not None:
            return max(self._bundle.duration, self._duration, 0.001)
        return max(self._duration, 0.001)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#111318"))

        rect = self._track_rect()
        duration = self._duration_seconds()

        painter.setPen(QColor("#828995"))
        ticks = 6
        for index in range(ticks + 1):
            ratio = index / ticks
            x = rect.left() + int(rect.width() * ratio)
            painter.drawLine(x, 18, x, 28)
            label = _fmt_time(duration * ratio)
            painter.drawText(x - 22, 14, 58, 14, Qt.AlignmentFlag.AlignLeft, label)

        results = self._bundle.results if self._bundle is not None else []
        lane_count = max(1, len(results))
        lane_height = max(32, rect.height() // lane_count)

        for lane_index in range(lane_count):
            top = rect.top() + lane_index * lane_height
            lane_rect = rect.adjusted(0, lane_index * lane_height, 0, 0)
            lane_rect.setHeight(lane_height - 3)
            painter.fillRect(
                lane_rect,
                QColor("#171a1f") if lane_index % 2 == 0 else QColor("#14171b"),
            )
            painter.setPen(QColor("#2d323a"))
            painter.drawLine(rect.left(), top + lane_height - 2, rect.right(), top + lane_height - 2)

            if lane_index >= len(results):
                continue

            result = results[lane_index]
            color = TRACK_COLORS[lane_index % len(TRACK_COLORS)]
            painter.setPen(QColor("#cfd4db"))
            painter.drawText(
                8,
                top,
                96,
                lane_height - 3,
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                result.name,
            )

            for segment in result.segments:
                x1 = rect.left() + int(rect.width() * segment.start / duration)
                x2 = rect.left() + int(rect.width() * segment.end / duration)
                clip = lane_rect.adjusted(x1 - rect.left() + 2, 5, x2 - rect.right() - 2, -5)
                if clip.width() < 5:
                    clip.setWidth(5)

                active = segment.start <= self._position_seconds <= segment.end
                fill = QColor(color)
                fill.setAlpha(225 if active else 150)
                painter.setPen(color.lighter(125) if active else color)
                painter.setBrush(fill)
                painter.drawRoundedRect(clip, 5, 5)

                if clip.width() > 72:
                    painter.setPen(QColor("#0a0d10"))
                    painter.drawText(
                        clip.adjusted(7, 0, -4, 0),
                        Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                        f"{segment.max_score:.2f}",
                    )

        playhead_ratio = min(1.0, max(0.0, self._position_seconds / duration))
        playhead_x = rect.left() + int(rect.width() * playhead_ratio)
        playhead_pen = QPen(QColor("#ff5d73"))
        playhead_pen.setWidth(2)
        painter.setPen(playhead_pen)
        painter.drawLine(playhead_x, 12, playhead_x, rect.bottom())
        painter.setBrush(QColor("#ff5d73"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPolygon(
            QPolygon(
                [
                    QPoint(playhead_x - 6, 8),
                    QPoint(playhead_x + 6, 8),
                    QPoint(playhead_x, 16),
                ]
            )
        )

        if self._bundle is None:
            painter.setPen(QColor("#777f8b"))
            painter.drawText(
                rect,
                Qt.AlignmentFlag.AlignCenter,
                "Analyze để tạo speaker tracks trên timeline",
            )

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt API
        rect = self._track_rect()
        if rect.width() <= 0 or event.position().x() < rect.left():
            return
        ratio = (event.position().x() - rect.left()) / rect.width()
        seconds = max(0.0, min(self._duration_seconds(), ratio * self._duration_seconds()))
        self.seekRequested.emit(seconds)
        super().mousePressEvent(event)
