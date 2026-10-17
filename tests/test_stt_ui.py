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
        assert window.inspector_tabs.tabText(1) == "STT"
        assert window.stt_panel.vad.isChecked()
        assert window.stt_panel.model.count() == 4
        assert window.stt_panel.raw_result is None
    finally:
        window.close()
        app.processEvents()
