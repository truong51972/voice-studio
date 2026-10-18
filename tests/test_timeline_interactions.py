"""Timeline drag gestures in Qt offscreen without inference backends."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt, QEvent
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from voice_studio.domain.timeline import TimelineClip, TimelineMap
from voice_studio.ui import create_application
from voice_studio.ui.widgets.timeline import EditorTimelineWidget


@pytest.fixture
def editor():
    app = create_application([])
    timeline = EditorTimelineWidget()
    timeline.resize(900, 280)
    clips = [
        TimelineClip("a", "source", 2., 12.),
        TimelineClip("b", "source", 20., 30.),
    ]
    mapping = TimelineMap(clips, {"source": 40.})
    timeline.set_project_data(mapping, [], [])
    timeline.show()
    app.processEvents()
    yield timeline
    timeline.close()
    app.processEvents()


def _mouse(widget, name, x, y, *, modifiers=Qt.KeyboardModifier.NoModifier):
    pos = QPoint(round(x), round(y))
    if name == "press":
        QTest.mousePress(widget, Qt.MouseButton.LeftButton, modifiers, pos)
    elif name == "release":
        QTest.mouseRelease(widget, Qt.MouseButton.LeftButton, modifiers, pos)
    else:
        QTest.mouseMove(widget, pos)


def test_zoomed_timeline_left_drag_pans_but_click_seeks(editor):
    widget = editor
    widget.set_view(zoom=4, pan=.5)
    rect = widget._track_rect()
    x = rect.left() + .8 * rect.width()
    y = rect.top() + 90
    seeks = []
    widget.seekRequested.connect(seeks.append)
    _mouse(widget, "press", x, y)
    _mouse(widget, "move", x - 120, y)
    _mouse(widget, "release", x - 120, y)
    assert widget._pan > .5
    assert seeks == []  # Dragging the canvas never starts playback/scrub.
    _mouse(widget, "press", x, y)
    _mouse(widget, "release", x, y)
    assert len(seeks) == 1
    assert seeks[-1] == pytest.approx(widget._seconds_at(x), abs=.07)


def test_drag_playhead_scrubs_with_immediate_position(editor):
    widget = editor
    widget.set_view(zoom=2, pan=0)
    widget.set_position_seconds(2.)
    rect = widget._track_rect()
    x = widget._x(2.)
    y = rect.top() + 70
    sent = []
    widget.seekRequested.connect(sent.append)
    _mouse(widget, "press", x, y)
    _mouse(widget, "move", widget._x(4.), y)
    _mouse(widget, "release", widget._x(4.), y)
    assert len(sent) >= 2
    assert sent[-1] == pytest.approx(4., abs=.1)


def test_shift_drag_selection_is_clamped_to_anchor_clip(editor):
    widget = editor
    widget.set_view(zoom=1, pan=0)
    rect = widget._track_rect()
    captures = []
    widget.selectionChangedClip.connect(lambda *values: captures.append(values))
    x1 = widget._x(8.)
    x2 = widget._x(14.)  # Crosses first clip boundary at project 10 s
    _mouse(widget, "press", x1, rect.top() + 30, modifiers=Qt.KeyboardModifier.ShiftModifier)
    _mouse(widget, "move", x2, rect.top() + 30)
    _mouse(widget, "release", x2, rect.top() + 30,
           modifiers=Qt.KeyboardModifier.ShiftModifier)
    assert len(captures) == 1
    clip, source_a, source_b = captures[0]
    assert clip == "a"
    assert source_a == pytest.approx(10., abs=.1)
    assert source_b == pytest.approx(12., abs=.1)
    assert widget._selection[0] == "a"


def test_wheel_zoom_preserves_pointer_anchor_and_emits_view_changed(editor):
    widget = editor
    widget.set_view(zoom=2, pan=.25)
    rect = widget._track_rect()
    x = rect.left() + .4 * rect.width()
    before = widget._seconds_at(x)
    views = []
    widget.viewChanged.connect(lambda z, p: views.append((z, p)))
    event = QWheelEvent(QPointF(x, 10.), QPointF(x, 10.),
                        QPoint(0, 0), QPoint(0, 120), Qt.MouseButton.NoButton,
                        Qt.KeyboardModifier.NoModifier,
                        Qt.ScrollPhase.ScrollUpdate, False)
    QApplication.sendEvent(widget, event)
    assert widget._zoom > 2
    assert widget._seconds_at(x) == pytest.approx(before, abs=.01)
    assert views and views[-1] == (widget._zoom, widget._pan)


def test_middle_button_pans_without_seeking(editor):
    widget = editor
    widget.set_view(zoom=4, pan=.4)
    rect = widget._track_rect()
    point = QPoint(rect.left() + 400, rect.top() + 40)
    sent = []
    widget.seekRequested.connect(sent.append)
    QTest.mousePress(widget, Qt.MouseButton.MiddleButton, Qt.KeyboardModifier.NoModifier, point)
    QTest.mouseMove(widget, point + QPoint(90, 0))
    QTest.mouseRelease(widget, Qt.MouseButton.MiddleButton, Qt.KeyboardModifier.NoModifier,
                       point + QPoint(90, 0))
    assert widget._pan < .4
    assert sent == []
