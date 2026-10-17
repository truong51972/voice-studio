import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from voice_studio.ui.panels.stt import STTPanel
from voice_studio.ui import create_application
import json
import pytest


@pytest.mark.parametrize('selection', [(1., 2.), None])
@pytest.mark.parametrize('kind', ['json', 'md', 'txt', 'srt'])
def test_single_source_selection_excludes_unselected_speech(tmp_path, monkeypatch, selection, kind):
    from PySide6.QtWidgets import QFileDialog
    app = create_application([])
    panel = STTPanel()
    output = tmp_path / f'selection.{kind}'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(output), ''))
    try:
        panel._show({'kind': 'stt', 'source': 'a.m4a', 'duration': 3., 'text': 'SECRET METADATA', 'segments': [
            {'id': 'before', 'start': 0., 'end': 1., 'text': 'SECRET BEFORE'},
            {'id': 'boundary', 'start': .5, 'end': 1.5, 'text': 'SECRET timed', 'words': [
                {'start': .5, 'end': .7, 'text': 'SECRET'}, {'start': 1.1, 'end': 1.2, 'text': ' timed'}]},
            {'id': 'inside', 'start': 1., 'end': 2., 'text': 'selected'},
            {'id': 'untimed', 'start': 1.5, 'end': 2.5, 'text': 'SECRET UNTIMED'},
            {'id': 'after', 'start': 2., 'end': 3., 'text': 'SECRET AFTER'}]})
        panel.export_selection.setChecked(True)
        panel.export_range = selection
        panel._export()
        if selection is None:
            assert not output.exists()
            assert 'valid source selection' in panel.status.text()
        else:
            assert 'SECRET' not in output.read_text()
            assert 'timed' in output.read_text() and 'selected' in output.read_text()
            if kind == 'json':
                payload = json.loads(output.read_text())
                assert payload['timebase'] == 'source seconds'
                assert [entry['text'] for entry in payload['selected_segments']] == ['timed', 'selected', '']
            elif kind == 'srt':
                assert output.read_text().count('-->') == 2
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


def test_apply_diarization_refreshes_automatic_labels_and_flags_in_standalone_panel():
    app = create_application([])
    panel = STTPanel()
    try:
        panel._show({'kind': 'stt', 'source': 'a.m4a', 'duration': 6., 'segments': [
            {'id': name, 'start': start, 'end': start + 2., 'text': name}
            for name, start in [('auto', 0.), ('human', 2.), ('ambiguous', 4.)]]})
        panel.apply_diarization([{'start': 0., 'end': 6., 'speaker_id': 'old'}])
        panel.document.replace('human', speaker_id='old', rename_speaker=True)
        panel.document.replace('auto', text='Human text correction')
        panel.apply_diarization([{'start': 0., 'end': 5., 'speaker_id': 'new'},
                                {'start': 5., 'end': 6., 'speaker_id': 'rival'}])
        assert panel.document.edited[0].speaker_id == 'new'
        assert panel.document.edited[0].text == 'Human text correction'
        assert panel.document.edited[1].speaker_id == 'old'
        assert panel.table.item(2, 2).text() == 'Review speaker'
        panel.apply_diarization([{'start': 0., 'end': 6., 'speaker_id': 'latest'}])
        assert panel.document.edited[2].speaker_id == 'latest'
        assert not panel.document.edited[2].speaker_review_required
        assert panel.document.edited[1].speaker_id == 'old'
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
