import json
from dataclasses import asdict
from pathlib import Path

import pytest

from voice_studio.projects import ProjectStore, _hash_file


def project_with_sources(tmp_path, count=2):
    project = ProjectStore(tmp_path / 'project')
    assets = []
    for index in range(count):
        path = tmp_path / f'source-{index}.m4a'
        path.write_bytes(bytes([index]) * 32)
        assets.append({'source': str(path), 'fingerprint': _hash_file(path), 'bytes': path.stat().st_size,
                       'mtime_ns': path.stat().st_mtime_ns, 'duration': 20., 'kind': 'audio'})
    project.import_assets(assets)
    return project


def diarize(project, media_id):
    record = project.queue_analysis(media_id, 'diarization', {'model_revision': 'local-v1'})
    turns = [dict(start=0., end=8., speaker_id='Speaker 1', cluster_id='cluster-0', overlap=False, confidence=None),
             dict(start=6., end=12., speaker_id='Speaker 2', cluster_id='cluster-1', overlap=True, confidence=None)]
    exclusive = [{**turns[0], 'end': 6.}, {**turns[1], 'overlap': False}]
    project.finish_analysis(record, {'kind': 'diarization', 'turns': turns, 'exclusive_turns': exclusive, 'speakers': ['Speaker 1', 'Speaker 2']})
    return record


def stt(project, media_id):
    record = project.queue_analysis(media_id, 'stt', {'model': 'fake-v1'})
    project.finish_analysis(record, {'kind': 'stt', 'source': project.get(media_id).source, 'duration': 20.,
        'segments': [{'id': 's1', 'start': 1., 'end': 3., 'text': 'hello'},
                     {'id': 's2', 'start': 10., 'end': 11., 'text': 'other voice'}]})
    return record


def test_independent_cluster_numbers_never_establish_project_identity(tmp_path):
    project = project_with_sources(tmp_path)
    first, second = [diarize(project, m.id) for m in project.items]
    a = project.mapped_turns(first)[0]['speaker_id']
    b = project.mapped_turns(second)[0]['speaker_id']
    assert a != b
    assert len(project.speakers) == 4
    project.rename_speaker(a, 'Alice')
    project.reorder_clips([c.id for c in reversed(project.clips)])
    reopened = ProjectStore(project.directory)
    assert reopened.mapped_turns(first)[0]['speaker_id'] == a
    assert reopened.speaker(a).name == 'Alice'
    assert reopened.mapped_turns(second)[0]['speaker_id'] == b


def test_confirmed_merge_updates_review_and_mapping_without_changing_raw(tmp_path):
    project = project_with_sources(tmp_path)
    first, second = [diarize(project, m.id) for m in project.items]
    transcripts = [stt(project, m.id) for m in project.items]
    a, b = project.mapped_turns(first)[0]['speaker_id'], project.mapped_turns(second)[0]['speaker_id']
    region = project.add_reference(b, project.items[1].id, 1., 4.)
    raw_before = {r.id: project.analysis_path(r.id).read_bytes() for r in project.analyses}
    project.merge_speakers(a, b)
    assert region.speaker_id == a
    assert project.review(project.items[1].id).edited[0].speaker_id == a
    assert project.speaker(b).id == a
    assert all(project.analysis_path(key).read_bytes() == value for key, value in raw_before.items())
    reopened = ProjectStore(project.directory)
    assert reopened.mapped_turns(second)[0]['speaker_id'] == a
    assert reopened.speaker(b).id == a
    # A split changes only the chosen source-local cluster.
    split = reopened.split_cluster(second.id, 'cluster-0', 'Bob')
    assert reopened.mapped_turns(first)[0]['speaker_id'] == a
    assert reopened.mapped_turns(second)[0]['speaker_id'] == split
    assert reopened.review(project.items[1].id).edited[0].speaker_id == split


def test_manual_corrections_survive_auto_assignment_and_raw_outputs_remain_separate(tmp_path):
    project = project_with_sources(tmp_path, 1)
    item = project.items[0]
    transcript = stt(project, item.id)
    document = project.review(item.id)
    document.replace('s1', text='Reviewed', speaker_id='Human correction', rename_speaker=True)
    project.save_review(item.id, document)
    record = diarize(project, item.id)
    reviewed = project.review(item.id)
    assert reviewed.edited[0].speaker_id == 'Human correction'
    assert reviewed.edited[0].text == 'Reviewed'
    assert reviewed.edited[1].speaker_id == project.mapped_turns(record, exclusive=True)[1]['speaker_id']
    assert project.result(transcript)['segments'][0].get('speaker_id') is None


def test_manual_regions_validate_overlap_bounds_and_allow_multiple_references(tmp_path):
    project = project_with_sources(tmp_path, 1)
    item = project.items[0]
    speaker = project.create_speaker('Manual')
    project.add_reference(speaker.id, item.id, 1., 4.)
    project.add_reference(speaker.id, item.id, 12., 16.)
    with pytest.raises(ValueError, match='at least 1 second'):
        project.add_reference(speaker.id, item.id, 0., .5)
    with pytest.raises(ValueError, match='inside'):
        project.add_reference(speaker.id, item.id, 0., 21.)
    diarize(project, item.id)
    with pytest.raises(ValueError, match='overlapping voices'):
        project.add_reference(speaker.id, item.id, 5., 9.)
    assert len(ProjectStore(project.directory).references) == 2


def test_cache_reuse_revisions_and_interrupted_analysis(tmp_path):
    project = project_with_sources(tmp_path, 1)
    item = project.items[0]
    completed = stt(project, item.id)
    running = project.queue_analysis(item.id, 'locator', {'profile': 'fast', 'model_revision': 'v1'})
    running.state = 'running'
    project.save()
    reopened = ProjectStore(project.directory)
    assert reopened.analyses[-1].state == 'interrupted'
    assert reopened.cached_analysis(item.id, 'stt', completed.settings).id == completed.id
    assert reopened.cached_analysis(item.id, 'stt', {'model': 'fake-v2'}) is None
    assert reopened.review(item.id).edited[0].text == 'hello'
    with pytest.raises(ValueError, match='not active'):
        reopened.finish_analysis(reopened.analyses[-1], {'kind': 'locator'})


def test_changed_relink_invalidates_references_and_cached_inference(tmp_path):
    project = project_with_sources(tmp_path, 1)
    item = project.items[0]
    speaker = project.create_speaker('A')
    region = project.add_reference(speaker.id, item.id, 1., 4.)
    record = stt(project, item.id)
    project.trim_clip(project.clips[0].id, 1., 10.)
    replacement = tmp_path / 'replacement.m4a'
    replacement.write_bytes(b'different audio')
    project.relink_asset(item.id, {'source': str(replacement), 'fingerprint': _hash_file(replacement),
        'bytes': replacement.stat().st_size, 'mtime_ns': replacement.stat().st_mtime_ns, 'duration': 3., 'kind': 'audio'})
    assert region.state == 'invalid'
    assert project.cached_analysis(item.id, 'stt', record.settings) is None
    assert project.clips[0].source_in == 0
    assert project.analysis_path(record.id).is_file()
    assert ProjectStore(project.directory).references[0].state == 'invalid'


def test_all_project_exports_follow_trim_order_and_keep_source_boundaries(tmp_path):
    project = project_with_sources(tmp_path)
    for item in project.items:
        stt(project, item.id)
    first, second = project.clips
    project.trim_clip(first.id, 2., 8.)
    project.reorder_clips([second.id, first.id])
    payload = json.loads(project.combined_export('json'))
    assert [clip['media_id'] for clip in payload['clips']] == [second.media_id, first.media_id]
    assert payload['clips'][1]['timeline_start'] == 20.
    assert payload['clips'][1]['selected_segments'][0]['start'] == 2.
    subtitles = project.combined_export('srt')
    assert subtitles.index('source-1.m4a') < subtitles.index('source-0.m4a')
    assert '00:00:20,000 --> 00:00:21,000' in subtitles
    assert project.review(first.media_id).edited[0].start == 1.


def test_project_summary_has_stable_source_anchors_and_ordered_review_snapshots(tmp_path):
    from voice_studio.summarization import summarize, summary_markdown
    project = project_with_sources(tmp_path)
    for item in project.items:
        stt(project, item.id)
    project.reorder_clips([c.id for c in reversed(project.clips)])
    snapshot = project.summary_document()
    first = snapshot.edited[0]
    assert first.text.startswith('[source-1.m4a]')
    assert first.start == 1.  # source-relative, not concatenated project time
    def requester(prompt, model):
        return {'items': [{'section': 'Topics', 'text': 'Fixture summary', 'source_ids': [first.id]}]}
    report = summarize(snapshot, model='fixture-only', requester=requester)
    assert report['items'][0]['source_anchors'][0]['media_id'] == project.items[1].id
    assert 'source-1.m4a 1.0–3.0s' in summary_markdown(report)


def test_reimport_keeps_speaker_links_and_reference_ids(tmp_path):
    project = project_with_sources(tmp_path, 1)
    item = project.items[0]
    analysis = diarize(project, item.id)
    speaker_id = project.mapped_turns(analysis)[0]['speaker_id']
    region = project.add_reference(speaker_id, item.id, 1., 4.)
    project.import_assets([asdict(item)])
    assert len(project.items) == 1
    assert project.references[0].id == region.id
    assert project.mapped_turns(analysis)[0]['speaker_id'] == speaker_id


def test_overlap_sweep_distinguishes_touches_and_same_voice_tracks():
    from voice_studio.domain.speakers import has_overlapping_voices
    turns = [{'start': 0., 'end': 5., 'speaker_id': 'a'}, {'start': 1., 'end': 3., 'speaker_id': 'a'},
             {'start': 5., 'end': 8., 'speaker_id': 'b'}]
    assert not has_overlapping_voices(turns, 0., 8.)
    turns.append({'start': 4., 'end': 6., 'speaker_id': 'b'})
    assert has_overlapping_voices(turns, 3., 5.)
    assert not has_overlapping_voices(turns, 6., 8.)
