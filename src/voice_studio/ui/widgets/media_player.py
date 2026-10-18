from __future__ import annotations

"""The existing preview overlay shares the playback source clock with STT review."""

from math import isfinite

from PySide6.QtCore import Qt, QRect
from PySide6.QtGui import QColor, QPainter
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import QWidget

from ...pipeline import AnalysisBundle
from ...subtitle_index import SubtitleIndex
from ..theme import TRACK_COLORS


def _subtitle_lines(text: str, metrics, width: int) -> list[str]:
    """Keep captions to at most two readable lines, eliding huge utterances."""
    words = " ".join(text.split()).split(" ")
    if not words or words == [""]:
        return []
    lines = []
    index = 0
    while index < len(words) and len(lines) < 2:
        current = ""
        while index < len(words):
            candidate = (current + " " + words[index]).strip()
            if current and metrics.horizontalAdvance(candidate) > width:
                break
            current = candidate
            index += 1
            if metrics.horizontalAdvance(current) > width:
                current = metrics.elidedText(current, Qt.TextElideMode.ElideRight, width)
                break
        if len(lines) == 1 and index < len(words):
            current = metrics.elidedText((current + " " + " ".join(words[index:])).strip(),
                                         Qt.TextElideMode.ElideRight, width)
            index = len(words)
        lines.append(current)
    return lines


class DetectionOverlay(QWidget):
    """Speaker/locator chips above a compact, optional reviewed subtitle."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._bundle: AnalysisBundle | None = None
        self._position_seconds = 0.0
        self._turns = []
        self._names = {}
        self._subtitle_names = {}
        self._subtitles = SubtitleIndex()
        self._show_subtitles = True
        self._inside_clip = True
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

    def set_bundle(self, bundle: AnalysisBundle | None) -> None:
        self._bundle = bundle
        self.update()

    def set_position(self, seconds: float, *, inside_clip: bool = True) -> None:
        self._position_seconds = max(0., seconds) if isfinite(seconds) else 0.
        self._inside_clip = inside_clip
        self.update()

    def set_turns(self, turns, names):
        self._turns, self._names = turns, names
        self.update()

    def set_subtitles(self, entries, names=None) -> None:
        self._subtitles.set_entries(entries)
        if names is not None:
            self._subtitle_names = names
        self.update()

    def set_show_subtitles(self, value: bool) -> None:
        self._show_subtitles = bool(value)
        self.update()

    def _active_results(self):
        if self._bundle is None:
            return []
        active = []
        for result in self._bundle.results:
            segment = next(
                (s for s in result.segments
                 if s.start <= self._position_seconds < s.end), None
            )
            if segment is not None:
                active.append((result, segment))
        return active

    def _paint_subtitle(self, painter: QPainter) -> int:
        if not self._show_subtitles or not self._inside_clip:
            return 0
        entry = self._subtitles.at(self._position_seconds)
        if entry is None:
            return 0
        width = max(1, self.width() - 44)
        if width < 70 or self.height() < 80:
            return 0
        font = painter.font()
        font.setPointSize(max(11, font.pointSize()))
        painter.setFont(font)
        metrics = painter.fontMetrics()
        lines = _subtitle_lines(entry.text, metrics, width - 24)
        if not lines:
            return 0
        speaker = (self._subtitle_names.get(entry.speaker_id, entry.speaker_id) or "") if not entry.speaker_review_required else ""
        height = 22 + len(lines) * (metrics.height() + 2) + (metrics.height() if speaker else 0)
        height = min(height, self.height() - 12)
        rect = QRect(18, self.height() - height - 12, self.width() - 36, height)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(9, 12, 18, 226))
        painter.drawRoundedRect(rect, 10, 10)
        painter.setPen(QColor("#a6dce7"))
        y = rect.top() + 8
        if speaker:
            painter.drawText(QRect(rect.left() + 12, y, rect.width() - 24, metrics.height()),
                             Qt.AlignmentFlag.AlignHCenter, str(speaker))
            y += metrics.height()
        painter.setPen(QColor("#ffffff"))
        for line in lines:
            painter.drawText(QRect(rect.left() + 12, y, rect.width() - 24, metrics.height() + 2),
                             Qt.AlignmentFlag.AlignHCenter, line)
            y += metrics.height() + 2
        return height + 12

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        subtitle_offset = self._paint_subtitle(painter)
        active = self._active_results()
        if not active and self._turns:
            labels = [self._names.get(t["speaker_id"], "Anonymous") + (" · overlap" if t.get("overlap") else "")
                      for t in self._turns if t["start"] <= self._position_seconds < t["end"]]
            if labels:
                bottom = self.height() - 12 - subtitle_offset
                painter.fillRect(QRect(8, bottom - 40, max(1, self.width() - 16), 40),
                                 QColor(10, 12, 16, 210))
                painter.setPen(QColor("#e7f4f7"))
                painter.drawText(QRect(18, bottom - 36, max(1, self.width() - 30), 32),
                                 Qt.AlignmentFlag.AlignVCenter, " · ".join(dict.fromkeys(labels)))
            return
        margin, chip_height, gap = 18, 36, 8
        y = self.height() - margin - subtitle_offset - chip_height
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
            painter.drawText(x + 20, y, width - 26, chip_height,
                             Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, label)
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
