import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from voice_studio.ui.panels.stt import STTPanel
from voice_studio.ui import create_application

def test_qt_editor_retains_raw_hypotheses_on_edit():
    app = create_application([])
    panel = STTPanel()
    try:
        panel._show({
            "kind": "stt", "source": "a.m4a", "duration": 2,
            "segments": [{"id": "s1", "start": 0.1, "end": 1.3, "text": "raw"}],
        })
        assert panel.table.rowCount() == 1
        panel.table.item(0, 3).setText("reviewed")
        assert panel.document.edited[0].text == "reviewed"
        assert panel.document.raw[0].text == "raw"
        panel.search.setText("reviewed")
        assert not panel.table.isRowHidden(0)
        panel.search.setText("missing")
        assert panel.table.isRowHidden(0)
        panel._reset()
        assert panel.document.edited[0].text == "raw"
    finally:
        panel.close()
        app.processEvents()
