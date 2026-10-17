import os
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtWidgets import QScrollArea

from voice_studio.ui import build_app, create_application
from voice_studio.ui.resources import _resource_path
from voice_studio.ui.timecode import milliseconds_to_seconds, seconds_to_milliseconds


@pytest.mark.parametrize("platform, configured, expected", [
    ("linux", None, "pulseaudio"),
    ("linux", "pipewire", "pipewire"),
    ("win32", None, None),
    ("darwin", None, None),
])
def test_application_audio_backend(monkeypatch, platform, configured, expected):
    from voice_studio.ui import main_window

    monkeypatch.delenv("QT_AUDIO_BACKEND", raising=False)
    if configured is not None:
        monkeypatch.setenv("QT_AUDIO_BACKEND", configured)
    monkeypatch.setattr(main_window, "sys", SimpleNamespace(platform=platform))
    existing = object()
    monkeypatch.setattr(main_window, "QApplication", SimpleNamespace(instance=lambda: existing))

    assert create_application([]) is existing
    assert os.environ.get("QT_AUDIO_BACKEND") == expected


def test_refactored_resources_and_player_clock():
    assert _resource_path("voice-studio.png").is_file()
    assert seconds_to_milliseconds(3.125) == 3125
    assert milliseconds_to_seconds(3125) == 3.125
    assert seconds_to_milliseconds(-1) == 0


def test_one_shared_qt_player_and_inspector_layout():
    app = create_application([])
    window = build_app()
    try:
        assert len(window.findChildren(QMediaPlayer)) == 1
        assert window.root_splitter.orientation() == Qt.Orientation.Vertical
        assert window.workspace_splitter.orientation() == Qt.Orientation.Horizontal
        assert window.analysis_page.findChildren(QScrollArea) == []
        assert [window.inspector_tabs.tabText(i) for i in range(3)] == [
            "Speakers", "STT", "Results",
        ]
        assert window.video_widget.overlay.parent() is window.video_widget
        assert window.windowTitle().startswith("Voice Studio")
        # A freshly created Qt slider has a 0..0 range, so duration must
        # be set before asserting that position updates are accepted.
        window._on_player_duration(60_000)
        assert window.timeline._duration == 60
        assert window.position_slider.maximum() == 60_000
        window._on_player_position(3000)
        assert window.timeline._position_seconds == 3
        assert window.video_widget.overlay._position_seconds == 3
        assert window.position_slider.value() == 3000
    finally:
        window.close()
        app.processEvents()


def test_source_package_exports_are_backward_compatible():
    from voice_studio import ui
    assert ui.MainWindow.__module__ == "voice_studio.ui.main_window"
    assert ui.EditorTimelineWidget.__module__ == "voice_studio.ui.widgets.timeline"
    assert ui._parse_timecode("01:10.0") == 70
