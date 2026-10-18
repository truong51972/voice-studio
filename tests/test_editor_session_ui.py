import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import time
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from voice_studio.projects import ProjectStore
from voice_studio.task_runtime import TaskRequest
from voice_studio.ui import build_app, create_application
from voice_studio.ui.session import ProjectSession


def settle(session, app, timeout=15):
    deadline = time.monotonic() + timeout
    while session.jobs and time.monotonic() < deadline:
        session.poll()
        app.processEvents()
        time.sleep(.02)
    assert not session.jobs, 'Project queue did not settle'


def recordings(tmp_path):
    paths = []
    for index in range(3):
        path = tmp_path / f'talk-{index}.wav'
        x = np.arange(16000 * 4) / 16000
        sf.write(path, .2 * np.sin(2 * np.pi * (220 + index * 220) * x), 16000)
        paths.append(str(path))
    return paths


def test_editor_import_trim_reorder_save_reopen_and_reference_controls(tmp_path):
    app = create_application([])
    project = ProjectStore(tmp_path / 'project')
    window = build_app()
    try:
        window.session.open(project)
        window.session.import_media(recordings(tmp_path))
        settle(window.session, app)
        assert len(project.items) == len(project.clips) == 3
        assert window.projects_panel.table.rowCount() == 3
        assert window.pages.currentIndex() == 1
        assert window.playback.project is project
        assert window.speakers_panel.mode.currentIndex() == 0
        first = project.clips[0]
        window.playback.select_clip(first.id)
        window._set_selection(.5, 2.5)
        assert window.speakers_panel.reference.start.value() == .5
        assert window.speakers_panel.reference.end.value() == 2.5
        window.clip_in.setValue(.5)
        window.clip_out.setValue(3.)
        window._trim_clip()
        window._move_clip(1)
        assert project.clips[1].id == first.id
        assert project.timeline().source_to_project(first.id, 1.) == 4.5
        window._set_selection(1., 2.)
        window._save()
        assert all(panel._manager is None for panel in (window.stt_panel, window.diarization_panel, window.summary_panel))
    finally:
        window.close()
        app.processEvents()
    reopened = build_app()
    try:
        reopened.projects_panel._open_folder(str(project.directory))
        settle(reopened.session, app)
        assert reopened._clip_id == first.id
        assert reopened.selection_start.value() == 1.
        assert reopened.selection_end.value() == 2.
        assert reopened.session.project.clips[1].id == first.id
        assert reopened.speakers_panel.reference.source.count() == 3
    finally:
        reopened.close()
        app.processEvents()


def test_project_switch_cancels_old_job_and_cannot_write_into_new_project(tmp_path):
    app = create_application([])
    project = ProjectStore(tmp_path / 'old')
    project.add([Path(recordings(tmp_path)[0])])
    project.items[0].duration = 4.
    session = ProjectSession()
    session.open(project)
    settle(session, app)
    record = project.queue_analysis(project.items[0].id, 'stt', {'model': 'test'})
    job = session.manager.submit(TaskRequest(kind='diagnostic', inputs={'seconds': 5., 'value': 'old'}))
    session.jobs[job] = record
    session.manager.poll()
    newer = ProjectStore(tmp_path / 'new')
    session.open(newer)
    try:
        assert record.state == 'cancelled'
        assert newer.analyses == []
        assert not list((newer.directory / 'results').glob('*'))
        assert ProjectStore(project.directory).analyses[-1].state == 'cancelled'
    finally:
        session.close()


def test_cached_result_reused_after_trim_and_all_models_use_one_queue(tmp_path):
    app = create_application([])
    project = ProjectStore(tmp_path / 'project')
    project.add([recordings(tmp_path)[0]])
    project.items[0].duration = 4.
    session = ProjectSession()
    session.open(project)
    settle(session, app)
    item = project.items[0]
    options = {'model_id': 'whisper-small', 'language': 'auto', 'vad': True, 'word_timestamps': False,
               'chunk_seconds': 30, 'device': 'cpu', 'compute_type': 'int8'}
    record = project.queue_analysis(item.id, 'stt', session.options_revision('stt', options))
    project.finish_analysis(record, {'kind': 'stt', 'source': item.source, 'duration': 4.,
        'segments': [{'id': 's1', 'start': 1., 'end': 2., 'text': 'cached'}]})
    original = project.analysis_path(record.id).read_bytes()
    turns = [dict(start=0., end=4., speaker_id='old', cluster_id='old', overlap=False)]
    first_diarization = project.queue_analysis(item.id, 'diarization', {'revision': 'v1'})
    project.finish_analysis(first_diarization, {'kind': 'diarization', 'turns': turns, 'exclusive_turns': turns})
    document = project.review(item.id)
    document.replace('s1', text='cached correction')
    project.save_review(item.id, document)
    # A newer transcript is active when v2 finishes; the archived cached review
    # still carries v1 attribution until it is activated again.
    newer_stt = project.queue_analysis(item.id, 'stt', {'revision': 'newer'})
    project.finish_analysis(newer_stt, {'kind': 'stt', 'segments': [
        {'id': 'new', 'start': 1., 'end': 2., 'text': 'newer transcript'}]})
    turns = [dict(start=0., end=4., speaker_id='new', cluster_id='new', overlap=False)]
    latest_diarization = project.queue_analysis(item.id, 'diarization', {'revision': 'v2'})
    project.finish_analysis(latest_diarization, {'kind': 'diarization', 'turns': turns, 'exclusive_turns': turns})
    project.trim_clip(project.clips[0].id, .5, 3.)
    received = []
    session.resultReady.connect(lambda task, media_id, payload: received.append((task, media_id, payload)))
    try:
        assert session.analyze('stt', item.id, options) is not None
        settle(session, app)
        assert session.jobs == {}
        assert received[0][2]['segments'][0]['text'] == 'cached'
        assert project.analysis_path(record.id).read_bytes() == original
        assert item.settings_key == record.id
        entry = project.review(item.id).edited[0]
        assert entry.text == 'cached correction'
        assert entry.speaker_id == project.cluster_mappings[latest_diarization.id]['new']
        assert entry.speaker_analysis_id == latest_diarization.id
    finally:
        session.close()


def test_failed_import_is_atomic_and_remains_visible_after_restart(tmp_path):
    app = create_application([])
    project = ProjectStore(tmp_path / 'project')
    session = ProjectSession()
    session.open(project)
    paths = recordings(tmp_path)
    session.import_media([paths[0], str(tmp_path / 'absent.m4a')])
    settle(session, app)
    session.close()
    reopened = ProjectStore(project.directory)
    assert reopened.items == []
    assert reopened.settings['operations'][-1]['state'] == 'failed'
    assert 'missing' in reopened.settings['operations'][-1]['error'].lower()


def test_cached_inference_rejects_changed_content_even_with_preserved_stat(tmp_path):
    app = create_application([])
    source = Path(recordings(tmp_path)[0])
    project = ProjectStore(tmp_path / 'project')
    project.add([source])
    project.items[0].duration = 4.
    session = ProjectSession()
    session.open(project)
    settle(session, app)
    item = project.items[0]
    options = {'model_id': 'whisper-small', 'language': 'auto', 'vad': True, 'word_timestamps': False,
               'chunk_seconds': 30, 'device': 'cpu', 'compute_type': 'int8'}
    record = project.queue_analysis(item.id, 'stt', session.options_revision('stt', options))
    project.finish_analysis(record, {'kind': 'stt', 'source': item.source, 'duration': 4.,
        'segments': [{'id': 's1', 'start': 1., 'end': 2., 'text': 'original'}]})
    before = source.stat()
    content = bytearray(source.read_bytes())
    content[-20] ^= 1
    source.write_bytes(content)
    os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns))
    received = []
    session.resultReady.connect(lambda *args: received.append(args))
    try:
        session.analyze('stt', item.id, options)
        settle(session, app)
        assert received == []
        assert item.status == 'changed'
        assert project.analyses[0].state == 'completed'  # old raw result is preserved
        assert project.settings['operations'][-1]['state'] == 'failed'
    finally:
        session.close()


def test_late_stt_result_cannot_save_old_corrections_under_new_analysis(tmp_path, monkeypatch):
    import json
    from voice_studio.transcript import TranscriptDocument
    from voice_studio.ui import main_window
    app = create_application([])
    project = ProjectStore(tmp_path / 'project')
    project.add([recordings(tmp_path)[0]])
    project.items[0].duration = 4.
    item = project.items[0]
    original = project.queue_analysis(item.id, 'stt', {'model': 'old'})
    project.finish_analysis(original, {'kind': 'stt', 'source': item.source, 'duration': 4.,
        'segments': [{'id': 's1', 'start': 1., 'end': 2., 'text': 'old raw'}]})
    window = build_app()
    try:
        window.session.open(project)
        settle(window.session, app)
        old_document = window.stt_panel.document
        newer = project.queue_analysis(item.id, 'stt', {'model': 'new'})
        window._before_result('stt', item.id)
        project.finish_analysis(newer, {'kind': 'stt', 'source': item.source, 'duration': 4.,
            'segments': [{'id': 's1', 'start': 1., 'end': 2., 'text': 'new raw'}]})
        # A modal editor keeps its old document until the dialog closes.
        monkeypatch.setattr(main_window.QApplication, 'activeModalWidget', lambda: object())
        window._result_ready('stt', item.id, project.result(newer))
        assert window.stt_panel.document is old_document
        old_document.replace('s1', text='Human correction to the old model')
        window._save_project_review()
        old_review = project.directory / 'reviews' / f'{item.id}-{original.id}.json'
        assert json.loads(old_review.read_text())['edited'][0]['text'] == 'Human correction to the old model'
        assert project.review(item.id).edited[0].text == 'new raw'
        monkeypatch.setattr(main_window.QApplication, 'activeModalWidget', lambda: None)
        window._refresh_pending_review()
        assert window.stt_panel.document.edited[0].text == 'new raw'
    finally:
        window.close()
        app.processEvents()


def test_project_switch_is_blocked_when_review_cannot_be_saved(tmp_path, monkeypatch):
    app = create_application([])
    project = ProjectStore(tmp_path / 'project')
    project.add([recordings(tmp_path)[0]])
    project.items[0].duration = 4.
    item = project.items[0]
    record = project.queue_analysis(item.id, 'stt', {})
    project.finish_analysis(record, {'kind': 'stt', 'source': item.source, 'duration': 4.,
        'segments': [{'id': 's1', 'start': 1., 'end': 2., 'text': 'raw'}]})
    window = build_app()
    try:
        window.session.open(project)
        settle(window.session, app)
        window.stt_panel.document.replace('s1', text='Unsaved correction')
        def denied(*args, **kwargs):
            raise PermissionError('reviews folder read-only')
        with monkeypatch.context() as patch:
            patch.setattr(project, 'save_review', denied)
            with pytest.raises(PermissionError, match='read-only'):
                window.session.open(ProjectStore(tmp_path / 'other'))
            assert window.session.project is project
            assert window.stt_panel.document.edited[0].text == 'Unsaved correction'
    finally:
        window.close()
        app.processEvents()


def test_pending_inline_text_is_committed_before_result_refresh(tmp_path):
    from PySide6.QtWidgets import QLineEdit
    app = create_application([])
    project = ProjectStore(tmp_path / 'project')
    project.add([recordings(tmp_path)[0]])
    item = project.items[0]
    item.duration = 4.
    record = project.queue_analysis(item.id, 'stt', {})
    project.finish_analysis(record, {'kind': 'stt', 'source': item.source, 'duration': 4.,
        'segments': [{'id': 's1', 'start': 1., 'end': 2., 'text': 'raw'}]})
    window = build_app()
    try:
        window.session.open(project)
        settle(window.session, app)
        window.inspector_tabs.setCurrentWidget(window.stt_panel)
        window.show()
        app.processEvents()
        table = window.stt_panel.table
        table.editItem(table.item(0, 3))
        app.processEvents()
        editor = table.findChild(QLineEdit)
        assert editor is not None
        editor.setText('Uncommitted keyboard text')
        window._before_result('diarization', item.id)
        assert project.review(item.id).edited[0].text == 'Uncommitted keyboard text'
        window._load_current_results()
        assert window.stt_panel.document.edited[0].text == 'Uncommitted keyboard text'
    finally:
        window.close()
        app.processEvents()
