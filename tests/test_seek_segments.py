import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QTableWidgetItem

from voice_studio.ui import _parse_timecode, build_app, create_application


def test_parse_timecode_seconds_and_minutes():
    assert _parse_timecode("8.5s") == pytest.approx(8.5)
    assert _parse_timecode("01:12.5") == pytest.approx(72.5)


def test_segment_click_seeks_native_media_player():
    class FakePlayer:
        def __init__(self):
            self.position = None
            self.paused = False

        def setPosition(self, position):  # noqa: N802 - mirrors Qt API
            self.position = position

        def pause(self):
            self.paused = True

    app = create_application([])
    window = build_app()
    try:
        window.segment_table.setRowCount(1)
        window.segment_table.setItem(0, 1, QTableWidgetItem("01:12.5"))
        fake = FakePlayer()
        window._player = fake
        window._seek_segment(0, 0)
        assert fake.position == 72_500
        assert fake.paused is True
    finally:
        window.close()
        app.processEvents()


def test_timeline_seek_uses_same_player_contract():
    class FakePlayer:
        def __init__(self):
            self.position = None
            self.paused = False

        def setPosition(self, position):  # noqa: N802 - mirrors Qt API
            self.position = position

        def pause(self):
            self.paused = True

    app = create_application([])
    window = build_app()
    try:
        fake = FakePlayer()
        window._player = fake
        window._seek_to_seconds(8.25)
        assert fake.position == 8_250
        assert fake.paused is True
    finally:
        window.close()
        app.processEvents()
