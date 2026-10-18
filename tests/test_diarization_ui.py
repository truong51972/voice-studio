import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from voice_studio.ui import build_app, create_application

def test_optional_diarization_keeps_one_player_and_raw_transcript_untouched():
    app = create_application([])
    window = build_app()
    try:
        from PySide6.QtMultimedia import QMediaPlayer
        assert len(window.findChildren(QMediaPlayer)) == 1
        assert window._advanced_inspector_pages["raw"][1] == "Raw AI"
        assert not window.inspector_tabs.isTabVisible(
            window.inspector_tabs.indexOf(window._advanced_inspector_pages["raw"][0]))
        window.stt_panel._show({
            "kind": "stt", "source": "a.wav", "duration": 3,
            "segments": [{"id": "s1", "start": 0, "end": 2, "text": "hello"}],
        })
        original = [
            {"start": 0, "end": 2, "speaker_id": "Speaker 1", "overlap": True},
            {"start": 1, "end": 3, "speaker_id": "Speaker 2", "overlap": True},
        ]
        exclusive = [
            {"start": 0, "end": 2, "speaker_id": "Speaker 1", "overlap": False},
        ]
        window.diarization_panel._show({"turns": original, "exclusive_turns": exclusive,
                                        "speakers": ["Speaker 1", "Speaker 2"]})
        assert window.diarization_panel.table.item(0, 3).text() == "Overlap"
        window.diarization_panel._apply()
        assert window.stt_panel.document.edited[0].speaker_id == "Speaker 1"
        assert window.stt_panel.document.raw[0].speaker_id is None
    finally:
        window.close()
        app.processEvents()
