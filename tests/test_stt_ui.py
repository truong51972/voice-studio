import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from voice_studio.ui import build_app, create_application
from voice_studio.ui.panels.stt import STTPanel

def test_stt_uses_existing_qt_media_player_and_inspector():
    app = create_application([])
    window = build_app()
    try:
        from PySide6.QtMultimedia import QMediaPlayer
        assert len(window.findChildren(QMediaPlayer)) == 1
        assert isinstance(window.stt_panel, STTPanel)
        assert window.inspector_tabs.tabText(0) == "Transcript"
        assert window.inspector_tabs.currentWidget() is window.stt_panel
        assert window.stt_panel.vad.isChecked()
        assert window.stt_panel.model.count() == 4
        assert window.stt_panel.raw_result is None
    finally:
        window.close()
        app.processEvents()


def test_large_transcript_highlights_playhead_without_stealing_selection():
    app = create_application([])
    window = build_app()
    try:
        panel = window.stt_panel
        panel._show({
            "kind": "stt", "source": "meeting.m4a", "duration": 3000.,
            "segments": [{"id": f"cue-{i}", "start": i * 2., "end": i * 2. + 1.5,
                          "text": f"Sentence {i}"} for i in range(1200)],
        })
        assert panel._cue_rows["cue-1000"] == 1000
        panel.table.selectRow(100)
        panel.set_playhead(2001.)
        assert panel._active_cue_row == 1000
        assert panel.table.currentRow() == 100  # Manual selection is never replaced.
        assert panel.table.item(1000, 3).background().color().name() == "#244752"
        panel._mark_user_navigation()
        previous_scroll = panel.table.verticalScrollBar().value()
        panel.set_playhead(1.)
        assert panel._active_cue_row == 0
        assert panel.table.currentRow() == 100
        assert panel.table.verticalScrollBar().value() == previous_scroll
        assert panel.table.item(1000, 3).background().style().name == "NoBrush"
        panel.follow_playhead.setChecked(False)
        panel._user_navigation_until = 0
        panel.set_playhead(2001.)
        assert panel.table.verticalScrollBar().value() == previous_scroll
        assert panel.table.currentRow() == 100
    finally:
        window.close()
        app.processEvents()
