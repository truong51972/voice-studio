import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from voice_studio.ui import build_app, create_application

def test_optional_diarization_keeps_one_player_and_raw_transcript_untouched():
    app = create_application([])
    window = build_app()
    try:
        from PySide6.QtMultimedia import QMediaPlayer
        assert len(window.findChildren(QMediaPlayer)) == 1
        assert window.inspector_tabs.tabText(5) == "Diarization"
        window.stt_panel._show({
            "kind": "stt", "source": "a.wav", "duration": 3,
            "segments": [{"id": "s1", "start": 0, "end": 2, "text": "hello"}],
        })
        window.stt_panel.apply_diarization([
            {"start": 0, "end": 2, "speaker_id": "Speaker 1", "overlap": False},
        ])
        assert window.stt_panel.document.edited[0].speaker_id == "Speaker 1"
        assert window.stt_panel.document.raw[0].speaker_id is None
    finally:
        window.close()
        app.processEvents()
