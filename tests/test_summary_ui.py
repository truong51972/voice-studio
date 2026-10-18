import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from voice_studio.ui import build_app, create_application

def test_optional_summary_is_separate_from_the_shared_media_player():
    app = create_application([])
    window = build_app()
    try:
        from PySide6.QtMultimedia import QMediaPlayer
        assert len(window.findChildren(QMediaPlayer)) == 1
        assert window._advanced_inspector_pages["summary"][1] == "Summary"
        assert not window.inspector_tabs.isTabVisible(
            window.inspector_tabs.indexOf(window.summary_panel))
        assert window.summary_panel.result is None
        assert window.summary_panel.model.text() == ""
        window.stt_panel._show({
            "kind": "stt", "source": "meeting.m4a", "duration": 2,
            "segments": [{"id": "s1", "start": 0, "end": 1, "text": "hi"}],
        })
        # Opening another media should not leak a previous AI report.
        window.summary_panel._show({
            "model": "local", "source": "meeting.m4a",
            "transcript_revision": 0, "items": [],
        })
        window.summary_panel.reset()
        assert window.summary_panel.result is None
        assert window.stt_panel.document.raw[0].text == "hi"
    finally:
        window.close()
        app.processEvents()
