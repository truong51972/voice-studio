import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from voice_studio.ui.panels.stt import STTPanel
from voice_studio.ui import create_application
import json
import pytest


@pytest.mark.parametrize('selection', [(1., 2.), None])
def test_single_source_json_selection_never_exports_full_raw_transcript(tmp_path, monkeypatch, selection):
    from PySide6.QtWidgets import QFileDialog
    app = create_application([])
    panel = STTPanel()
    output = tmp_path / 'selection.json'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(output), 'JSON (*.json)'))
    try:
        panel._show({'kind': 'stt', 'source': 'a.m4a', 'duration': 3., 'text': 'SECRET METADATA', 'segments': [
            {'id': 'before', 'start': 0., 'end': 1., 'text': 'SECRET BEFORE'},
            {'id': 'inside', 'start': 1., 'end': 2., 'text': 'selected'},
            {'id': 'after', 'start': 2., 'end': 3., 'text': 'SECRET AFTER'}]})
        panel.export_selection.setChecked(True)
        panel.export_range = selection
        panel._export()
        if selection is None:
            assert not output.exists()
            assert 'valid source selection' in panel.status.text()
        else:
            assert 'SECRET' not in output.read_text()
            payload = json.loads(output.read_text())
            assert payload['timebase'] == 'source seconds'
            assert [entry['text'] for entry in payload['selected_segments']] == ['selected']
    finally:
        panel.close()
        app.processEvents()


def test_ambiguous_speaker_is_visible_and_human_assignment_clears_flag(monkeypatch):
    from PySide6.QtWidgets import QInputDialog
    app = create_application([])
    panel = STTPanel()
    try:
        panel._show({'kind': 'stt', 'source': 'a.m4a', 'duration': 1., 'segments': [
            {'id': 'a', 'start': 0., 'end': 1., 'text': 'speech', 'speaker_review_required': True}]})
        assert panel.table.item(0, 2).text() == 'Review speaker'
        panel.table.selectRow(0)
        monkeypatch.setattr(QInputDialog, 'getText', lambda *args, **kwargs: ('Alice', True))
        panel._speaker()
        assert panel.document.edited[0].speaker_id == 'Alice'
        assert panel.document.edited[0].speaker_source == 'human'
        assert not panel.document.edited[0].speaker_review_required
    finally:
        panel.close()
        app.processEvents()

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
