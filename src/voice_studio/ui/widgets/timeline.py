from __future__ import annotations

"""Speaker tracks over a source-local seconds timebase."""

from PySide6.QtCore import QPoint, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPolygon
from PySide6.QtWidgets import QScrollBar, QWidget
from math import floor, log10
from time import monotonic

from ...pipeline import AnalysisBundle
from ...domain.timeline import map_time
from ..theme import TRACK_COLORS
from ..timecode import _fmt_time

class EditorTimelineWidget(QWidget):
    """Video-editor style speaker tracks with ruler, clips and a synced playhead."""

    seekRequested = Signal(float)
    selectionChanged = Signal(str, float, float)
    selectionChangedClip = Signal(str, float, float)
    viewChanged = Signal(float, float)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._bundle: AnalysisBundle | None = None
        self._duration = 0.0
        self._position_seconds = 0.0
        self._project_map = None
        self._sources = []
        self._annotations = []
        self._zoom = 1.
        self._pan = 0.
        self._drag_start = None
        self._drag_mode = None
        self._drag_origin_x = 0.
        self._drag_origin_pan = 0.
        self._drag_last_seek = 0.
        self._drag_preview = None
        self._drag_clip = None
        self._selection = None
        self._follow_suspended_until = 0.
        self._lane_names = []
        self._lane_positions = {}
        self.setMouseTracking(True)
        self._track_scroll = QScrollBar(Qt.Orientation.Vertical, self)
        self._track_scroll.hide()
        self._track_scroll.valueChanged.connect(lambda _value: self.update())
        self.setMinimumHeight(205)

    def set_bundle(self, bundle: AnalysisBundle | None) -> None:
        self._bundle = bundle
        if bundle is not None:
            self._duration = max(self._duration, bundle.duration)
        self.update()

    def set_duration_seconds(self, duration: float) -> None:
        self._duration = max(0.0, float(duration))
        self.update()

    def set_position_seconds(self, seconds: float, *, follow: bool = False) -> None:
        self._position_seconds = max(0.0, float(seconds))
        # Follow only active playback, not paused seeks, dragging, or a viewport
        # the user intentionally panned. Keep the playhead inside a 15–85%
        # comfort window to avoid the whole timeline jumping every frame.
        if (follow and self._project_map and self._zoom > 1.
                and self._drag_mode is None and monotonic() >= self._follow_suspended_until):
            start, span = self._view()
            duration = self._duration_seconds()
            target = None
            if seconds > start + span * .85:
                target = seconds - span * .65
            elif seconds < start + span * .15:
                target = seconds - span * .15
            if target is not None:
                available = duration - span
                self.set_view(pan=target / available if available > 0 else 0.)
                return
        self.update()

    def _track_rect(self):
        return self.rect().adjusted(112, 30, -16, -16)

    def _duration_seconds(self) -> float:
        if self._project_map is not None:
            return max(.001, self._project_map.duration)
        if self._bundle is not None:
            return max(self._bundle.duration, self._duration, 0.001)
        return max(self._duration, 0.001)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().paintEvent(event)
        if self._project_map is not None:
            self._paint_project()
            return
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

    def _inside_track(self, x: float, y: float) -> bool:
        rect = self._track_rect()
        return rect.left() <= x <= rect.right() and 0 <= y <= rect.bottom()

    def _seek_at(self, x: float, *, force: bool = False) -> None:
        seconds = self._seconds_at(x)
        self.set_position_seconds(seconds)
        now = monotonic()
        if force or now - self._drag_last_seek >= .04:
            self._drag_last_seek = now
            self.seekRequested.emit(seconds)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        x, y = event.position().x(), event.position().y()
        if not self._inside_track(x, y):
            return super().mousePressEvent(event)
        button = event.button()
        if button not in (Qt.MouseButton.LeftButton, Qt.MouseButton.MiddleButton,
                          Qt.MouseButton.RightButton):
            return super().mousePressEvent(event)
        if self._project_map is not None and not self._project_map.clips:
            return
        self._drag_origin_x = x
        self._drag_origin_pan = self._pan
        self._drag_start = self._seconds_at(x)
        self._drag_preview = None
        self._drag_clip = None
        if button in (Qt.MouseButton.MiddleButton, Qt.MouseButton.RightButton):
            self._drag_mode = "pan"
        elif event.modifiers() & Qt.KeyboardModifier.ShiftModifier and self._project_map:
            self._drag_mode = "select"
            self._drag_clip, _ = self._project_map.project_to_source(self._drag_start)
            self._drag_preview = (self._drag_start, self._drag_start)
        elif (self._zoom > 1. and y >= 30
              and not event.modifiers() & Qt.KeyboardModifier.ControlModifier
              and abs(x - self._x(self._position_seconds)) > 11):
            # Drag empty canvas to pan, short click still seeks.
            self._drag_mode = "pan"
        else:
            # Ruler, playhead, Ctrl+drag and unzoomed canvas scrub.
            self._drag_mode = "scrub"
            self._seek_at(x, force=True)
        self.grabMouse()
        self.setCursor(Qt.CursorShape.ClosedHandCursor if self._drag_mode == "pan"
                       else Qt.CursorShape.CrossCursor if self._drag_mode == "select"
                       else Qt.CursorShape.SizeHorCursor)
        event.accept()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        x = event.position().x()
        if self._drag_mode is None:
            self._update_cursor(x, event.position().y())
            return super().mouseMoveEvent(event)
        if self._drag_mode == "pan":
            if self._zoom > 1.:
                available = self._duration_seconds() * (1. - 1. / self._zoom)
                shift_seconds = ((self._drag_origin_x - x) * self._view()[1] /
                                 max(1., self._track_rect().width()))
                if available > 0:
                    self.set_view(pan=self._drag_origin_pan + shift_seconds / available, user=True)
        elif self._drag_mode == "scrub":
            self._seek_at(x)
        elif self._drag_mode == "select":
            self._drag_preview = (self._drag_start, self._seconds_at(x))
            self.update()
        event.accept()

    def _update_cursor(self, x: float, y: float) -> None:
        if not self._inside_track(x, y):
            self.unsetCursor()
        elif abs(x - self._x(self._position_seconds)) <= 11 or y < 30:
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        elif self._zoom > 1.:
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        else:
            self.setCursor(Qt.CursorShape.SizeHorCursor)

    def leaveEvent(self, event) -> None:  # noqa: N802
        if self._drag_mode is None:
            self.unsetCursor()
        super().leaveEvent(event)

    def set_project_data(self, mapping, sources, annotations):
        self._project_map = mapping
        self._sources = sources
        self._annotations = annotations
        self._lane_names = list(dict.fromkeys(a["lane"] for a in annotations))
        self._lane_positions = {name: index for index, name in enumerate(self._lane_names)}
        self._duration = mapping.duration if mapping else 0.
        self.update()

    def set_view(self, zoom=None, pan=None, *, user=False):
        if user:
            self._follow_suspended_until = monotonic() + 5.
        previous = self._zoom, self._pan
        if zoom is not None:
            self._zoom = max(1., min(128., float(zoom)))
        if pan is not None:
            self._pan = max(0., min(1., float(pan)))
        if previous != (self._zoom, self._pan):
            self.viewChanged.emit(self._zoom, self._pan)
        self.update()

    def update_annotations(self, annotations):
        """Replace annotation data without discarding waveform and clip caches."""
        self._annotations = annotations
        self._lane_names = list(dict.fromkeys(a["lane"] for a in annotations))
        self._lane_positions = {name: i for i, name in enumerate(self._lane_names)}
        self.update()

    def set_selection(self, clip_id, start, end):
        self._selection = (clip_id, start, end)
        self.update()

    def _view(self):
        span = self._duration_seconds() / self._zoom
        start = self._pan * (self._duration_seconds() - span)
        return start, span

    def _seconds_at(self, x):
        start, span = self._view()
        rect = self._track_rect()
        return max(0., min(self._duration_seconds(), start + (x - rect.left()) / max(1, rect.width()) * span))

    def _x(self, seconds):
        start, span = self._view()
        return self._track_rect().left() + (seconds - start) / max(.001, span) * self._track_rect().width()

    def _paint_project(self):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#111318"))
        rect = self._track_rect()
        start, span = self._view()
        painter.setPen(QColor("#aeb4bd"))
        painter.drawText(8, 16, "Project time")
        raw_tick = max(.001, span / max(2, self.width() // 140))
        order = 10 ** floor(log10(raw_tick))
        tick = next((step * order for step in (1, 2, 5, 10) if step * order >= raw_tick), 10 * order)
        first_tick = floor(start / tick) * tick
        for index in range(200):
            seconds = first_tick + index * tick
            if seconds > start + span:
                break
            if seconds < start:
                continue
            x = round(self._x(seconds))
            painter.drawText(x - 20, 16, _fmt_time(seconds))
            painter.drawLine(x, 20, x, rect.bottom())
        painter.save()
        painter.setClipRect(rect)
        for source in self._sources:
            clip = source["clip"]
            timeline_start = self._project_map.starts[clip.id]
            timeline_end = timeline_start + clip.end(source["duration"]) - clip.source_in
            x1, x2 = self._x(timeline_start), self._x(timeline_end)
            if x2 < rect.left() or x1 > rect.right():
                continue
            body = QRectF(x1 + 1, rect.top(), max(2., x2 - x1 - 2), 50)
            painter.setPen(QColor("#36c5d8"))
            painter.setBrush(QColor("#183944"))
            painter.drawRoundedRect(body, 3, 3)
            painter.drawText(body.adjusted(5, 1, -3, -26), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, source["name"])
            peaks = source.get("peaks", [])
            if peaks:
                # Read only visible waveform buckets and aggregate to screen pixels.
                visible_start = max(timeline_start, start)
                visible_end = min(timeline_end, start + span)
                first = max(0, int((clip.source_in + visible_start - timeline_start) / .1))
                last = min(len(peaks), int((clip.source_in + visible_end - timeline_start) / .1) + 1)
                step = max(1, (last - first) // max(1, int(rect.width())))
                painter.setPen(QColor("#50bfd0"))
                for bucket in range(first, last, step):
                    source_seconds = bucket * .1
                    if not clip.source_in <= source_seconds <= clip.end(source["duration"]):
                        continue
                    x = self._x(self._project_map.source_to_project(clip.id, source_seconds))
                    amplitude = max(peaks[bucket:min(last, bucket + step)], default=0.)
                    painter.drawLine(round(x), rect.top() + 36 - round(amplitude * 14), round(x), rect.top() + 36 + round(amplitude * 14))
        lanes = self._lane_names
        lane_positions = self._lane_positions
        visible = max(1, (rect.height() - 56) // 24)
        self._track_scroll.setGeometry(self.width() - 14, rect.top() + 56, 12, max(1, rect.height() - 56))
        self._track_scroll.setRange(0, max(0, len(lanes) - visible))
        self._track_scroll.setVisible(len(lanes) > visible)
        offset = self._track_scroll.value()
        height = max(22, (rect.height() - 56) // max(1, min(visible, len(lanes))))
        for annotation in self._annotations:
            lane = lane_positions[annotation["lane"]] - offset
            if lane < 0 or lane >= visible:
                continue
            y = rect.top() + 56 + lane * height
            x1, x2 = self._x(annotation["start"]), self._x(annotation["end"])
            if x2 < rect.left() or x1 > rect.right():
                continue
            color = QColor(annotation.get("color", "#36c5d8"))
            color.setAlpha(115 if annotation.get("overlap") else 180)
            painter.setBrush(color)
            painter.setPen(QColor("#b7c9d0"))
            body = QRectF(x1, y, max(3., x2 - x1), height - 4)
            painter.drawRoundedRect(body, 3, 3)
            painter.setPen(QColor("#eef6f8"))
            painter.drawText(body.adjusted(4, 0, -2, 0), Qt.AlignmentFlag.AlignVCenter,
                             annotation.get("text", "") + (" · overlap" if annotation.get("overlap") else ""))
        if self._drag_preview is not None:
            a, b = sorted(self._drag_preview)
            painter.fillRect(QRectF(self._x(a), rect.top(), max(0., self._x(b) - self._x(a)),
                                    rect.height()), QColor(54, 197, 216, 75))
        if self._selection:
            clip_id, a, b = self._selection
            try:
                a = self._project_map.source_to_project(clip_id, a)
                b = self._project_map.source_to_project(clip_id, b)
                painter.fillRect(QRectF(self._x(a), rect.top(), self._x(b) - self._x(a), rect.height()), QColor(54, 197, 216, 45))
            except ValueError:
                pass
        playhead_x = round(self._x(self._position_seconds))
        painter.setPen(QPen(QColor("#ff5d73"), 2))
        painter.drawLine(playhead_x, rect.top(), playhead_x, rect.bottom())
        painter.restore()
        # Visually expose the draggable handle at the top of the ruler.
        if rect.left() <= playhead_x <= rect.right():
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#ff5d73"))
            painter.drawPolygon(QPolygon([
                QPoint(playhead_x - 7, 19), QPoint(playhead_x + 7, 19),
                QPoint(playhead_x, 28),
            ]))
        painter.setPen(QColor("#aeb4bd"))
        painter.drawText(8, rect.top() + 27, "Sources")
        for index, lane in enumerate(lanes[offset:offset + visible]):
            painter.drawText(8, rect.top() + 56 + index * height + 17, lane[:15])

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._drag_mode is None:
            return super().mouseReleaseEvent(event)
        if event.button() not in (Qt.MouseButton.LeftButton, Qt.MouseButton.MiddleButton,
                                  Qt.MouseButton.RightButton):
            return
        mode = self._drag_mode
        self._drag_mode = None
        self._drag_preview = None
        self.releaseMouse()
        self._update_cursor(event.position().x(), event.position().y())
        if mode == "pan":
            if event.button() == Qt.MouseButton.LeftButton and abs(event.position().x() - self._drag_origin_x) < 4:
                self._seek_at(event.position().x(), force=True)
        elif mode == "scrub":
            self._seek_at(event.position().x(), force=True)
        elif mode == "select" and self._drag_clip is not None:
            # Clamp to anchor clip: never mix source-relative times across cuts.
            clip = self._drag_clip
            begin = self._project_map.starts[clip.id]
            end = begin + clip.end(self._project_map.durations[clip.media_id]) - clip.source_in
            a = max(begin, min(end, self._drag_start))
            b = max(begin, min(end, self._seconds_at(event.position().x())))
            a, b = sorted((a, b))
            if b > a and abs(self._x(b) - self._x(a)) >= 4:
                source_a = map_time(clip, begin, a, self._project_map.durations[clip.media_id], to_source=True)
                source_b = map_time(clip, begin, b, self._project_map.durations[clip.media_id], to_source=True)
                self.set_selection(clip.id, source_a, source_b)
                self.selectionChangedClip.emit(clip.id, source_a, source_b)
                self.selectionChanged.emit(clip.media_id, source_a, source_b)
        self._drag_clip = None
        self._drag_start = None
        self.update()
        event.accept()

    def wheelEvent(self, event):  # noqa: N802
        if self._project_map is None:
            return super().wheelEvent(event)
        delta = event.angleDelta().y() / 120.
        if not delta:
            delta = event.pixelDelta().y() / 120.
        if not delta:
            return super().wheelEvent(event)
        if event.modifiers() & Qt.KeyboardModifier.AltModifier:
            self._track_scroll.setValue(self._track_scroll.value() - round(delta))
        elif event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            if self._zoom > 1.:
                self.set_view(pan=self._pan - delta / (8. * self._zoom), user=True)
        else:
            # Cursor-anchored zoom: the point under the pointer stays fixed.
            ratio = max(0., min(1., (event.position().x() - self._track_rect().left()) /
                                max(1., self._track_rect().width())))
            anchor = self._seconds_at(event.position().x())
            target_zoom = max(1., min(128., self._zoom * 1.25 ** delta))
            duration = self._duration_seconds()
            span = duration / target_zoom
            available = duration - span
            new_pan = ((anchor - ratio * span) / available) if available > 0 else 0.
            self.set_view(zoom=target_zoom, pan=new_pan, user=True)
        event.accept()
