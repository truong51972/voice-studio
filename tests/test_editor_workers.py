from dataclasses import asdict
import subprocess

import numpy as np
import pytest
import soundfile as sf

from voice_studio import editor_tasks
from voice_studio.editor_tasks import probe_media, reference_embedding, run_editor_task, stream_windows
from voice_studio.media import ffmpeg_executable
from voice_studio.projects import ProjectStore


@pytest.fixture
def source(tmp_path):
    rate = 16000
    samples = np.arange(rate * 12) / rate
    tone = np.where(samples < 6, 220, 880)
    wav = tmp_path / 'source.wav'
    sf.write(wav, .2 * np.sin(2 * np.pi * tone * samples), rate)
    return wav


class ToneEmbedder:
    def __init__(self):
        self.calls = 0
        self.maximum_samples = 0
    def compute(self, samples, sample_rate=16000):
        self.calls += 1
        self.maximum_samples = max(self.maximum_samples, len(samples))
        frequency = np.fft.rfftfreq(len(samples), 1 / sample_rate)[np.argmax(np.abs(np.fft.rfft(samples)))]
        return np.array([1., 0.]) if frequency < 500 else np.array([0., 1.])


def test_import_three_real_aac_sources_and_stream_cached_waveforms(tmp_path, source):
    paths = []
    for index in range(3):
        path = tmp_path / f'talk-{index}.m4a'
        subprocess.run([str(ffmpeg_executable()), '-nostdin', '-v', 'error', '-i', str(source), '-c:a', 'aac', str(path)], check=True)
        paths.append(str(path))
    project = ProjectStore(tmp_path / 'project')
    payload = run_editor_task({'action': 'import', 'paths': paths, 'project_directory': str(project.directory)}, lambda stage: None)
    project.import_assets(payload['assets'])
    assert len(project.clips) == 3
    assert all(item.kind == 'audio' and item.duration == pytest.approx(12., abs=.1) for item in project.items)
    assert [item.source for item in project.items] == paths
    assert len(list((project.directory / 'cache').glob('waveform-*.json'))) == 1  # identical content shares a cache
    assert project.timeline().duration == pytest.approx(36., abs=.3)


def test_reference_decodes_only_region_and_invalidates_model_cache(tmp_path, source):
    metadata = probe_media(source)
    region = {'start': 7., 'end': 10., 'fingerprint': metadata['fingerprint']}
    embedder = ToneEmbedder()
    vector = reference_embedding(region, metadata, tmp_path, embedder, 'model-v1')
    np.testing.assert_allclose(vector, [0, 1])
    assert embedder.maximum_samples == 3 * 16000
    reference_embedding(region, metadata, tmp_path, embedder, 'model-v1')
    assert embedder.calls == 1
    reference_embedding(region, metadata, tmp_path, embedder, 'model-v2')
    assert embedder.calls == 2
    with pytest.raises(ValueError, match='changed'):
        reference_embedding({**region, 'fingerprint': 'stale'}, metadata, tmp_path, embedder, 'model-v1')


def test_silent_reference_is_rejected_with_guidance(tmp_path):
    path = tmp_path / 'silent.wav'
    sf.write(path, np.zeros(16000 * 3, dtype=np.float32), 16000)
    metadata = probe_media(path)
    with pytest.raises(ValueError, match='silent/too quiet'):
        reference_embedding({'start': 0., 'end': 3., 'fingerprint': metadata['fingerprint']}, metadata, tmp_path, ToneEmbedder(), 'v1')


def test_streamed_window_grid_matches_existing_locator_and_handles_61_minutes(monkeypatch):
    def chunks(path, chunk_seconds):
        for index in range(122):
            yield index * 30., np.ones(16000 * 30, dtype=np.float32)
    monkeypatch.setattr(editor_tasks, 'stream_audio', chunks)
    count = 0
    for start, end, samples in stream_windows('long.m4a'):
        count += 1
        assert len(samples) == 40000
        assert end - start == 2.5
    assert count == int((3660. - 2.5) / .5) + 1
    assert end == 3660.


def test_manual_matching_preserves_profiles_and_raw_window_scores(tmp_path, source, monkeypatch):
    metadata = probe_media(source)
    metadata['id'] = 'source'
    project = ProjectStore(tmp_path / 'project')
    project.import_assets([{k: v for k, v in metadata.items() if k != 'id'}])
    metadata['id'] = project.items[0].id
    speaker = project.create_speaker('First voice')
    region = project.add_reference(speaker.id, metadata['id'], 1., 4.)
    region.state = 'ready'
    embedder = ToneEmbedder()
    monkeypatch.setattr(editor_tasks, '_embedder', lambda profile: (embedder, 'verified-model-v1'))
    inputs = {'action': 'locator', 'project_directory': str(project.directory), 'target_path': str(source),
        'fingerprint': metadata['fingerprint'], 'media_kind': 'audio',
        'options': {'profile': 'fast', 'threshold': .6}, 'media': [metadata],
        'references': [asdict(region)], 'speakers': [asdict(speaker)]}
    result = run_editor_task(inputs, lambda stage: None)
    assert result['results'][0]['key'] == speaker.id
    assert result['results'][0]['segments']
    assert max(row['end'] for row in result['results'][0]['segments']) < 9.
    assert embedder.maximum_samples <= 10 * 16000


def test_speaker_comparison_returns_proposals_without_applying_merges(tmp_path, source):
    metadata = probe_media(source)
    metadata['id'] = 'm1'
    turns = [{'start': 0., 'end': 4., 'overlap': False}]
    inputs = {'project_directory': str(tmp_path), 'media': [metadata], 'references': [], 'options': {'threshold': .6},
              'clusters': [{'media_id': 'm1', 'speaker_id': speaker, 'turns': turns} for speaker in ('a', 'b', 'c')]}
    result = editor_tasks.reconcile(inputs, ToneEmbedder(), 'v1')
    assert len(result['proposals']) == 3
    assert all(proposal['ambiguous'] for proposal in result['proposals'])
    assert all('confidence' not in proposal and 'state' not in proposal for proposal in result['proposals'])


def test_media_kind_comes_from_streams_even_with_misleading_extension(tmp_path, source):
    video = tmp_path / 'video.mp4'
    subprocess.run([str(ffmpeg_executable()), '-nostdin', '-v', 'error', '-f', 'lavfi', '-i',
                    'color=c=black:s=64x64:d=1', '-i', str(source), '-t', '1', '-c:v', 'mpeg4',
                    '-c:a', 'aac', str(video)], check=True)
    renamed = video.with_suffix('.wav')
    video.rename(renamed)
    assert probe_media(renamed)['kind'] == 'video'
    assert probe_media(source)['kind'] == 'audio'
