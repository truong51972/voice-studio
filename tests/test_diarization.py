from types import SimpleNamespace
from voice_studio.diarization import _speaker_turns, attribute_segments


def test_dominance_counts_union_and_requires_coverage_and_a_clear_lead():
    from voice_studio.diarization import dominant_speaker
    turns = [{'start': 0., 'end': 2., 'speaker_id': 'a'}] * 3
    turns.append({'start': 2., 'end': 4., 'speaker_id': 'b'})
    assert dominant_speaker(0., 4., turns) is None  # duplicate tracks cannot create dominance
    assert dominant_speaker(0., 5., turns[:1]) is None  # less than 50% coverage
    assert dominant_speaker(0., 4., turns[:1]) == 'a'  # exactly 50% is sufficient without a rival
    assert dominant_speaker(0., 4., turns + [{'start': 0., 'end': 2.5, 'speaker_id': 'a'}]) is None
    assert dominant_speaker(0., 4., turns + [{'start': 0., 'end': 2.6, 'speaker_id': 'a'}]) == 'a'

def test_anonymous_speaker_turns_and_overlap_detection():
    class FakeAnnotation:
        def itertracks(self, yield_label=False):
            assert yield_label
            return iter([
                (SimpleNamespace(start=0.0, end=3.0), "-", "cluster_2"),
                (SimpleNamespace(start=2.0, end=4.0), "-", "cluster_3"),
                (SimpleNamespace(start=4.1, end=6.0), "-", "cluster_2"),
            ])
    output = SimpleNamespace(
        exclusive_speaker_diarization=None,
        speaker_diarization=FakeAnnotation()
    )
    turns = _speaker_turns(output)
    assert turns[0]["speaker_id"] == "Speaker 1"
    assert turns[1]["speaker_id"] == "Speaker 2"
    assert turns[0]["overlap"] is True
    assert turns[2]["overlap"] is False
    assert all(t["confidence"] is None for t in turns)

def test_conservative_timestamp_attribution_leaves_ambiguous_unassigned():
    segments = [
        {"id": "a", "start": 0, "end": 2, "text": "xin chào"},
        {"id": "b", "start": 2, "end": 4, "text": "hello"},
    ]
    turns = [
        {"start": 0, "end": 2, "speaker_id": "Speaker 1", "overlap": False},
        {"start": 2, "end": 3, "speaker_id": "Speaker 1", "overlap": False},
        {"start": 3, "end": 4, "speaker_id": "Speaker 2", "overlap": False},
    ]
    assigned = attribute_segments(segments, turns)
    assert assigned[0]["speaker_id"] == "Speaker 1"
    assert assigned[1].get("speaker_id") is None
    assert segments[0].get("speaker_id") is None


def test_original_overlap_and_exclusive_tracks_share_cluster_mapping():
    class Annotation:
        def __init__(self, rows):
            self.rows = rows
        def itertracks(self, yield_label=False):
            return iter((SimpleNamespace(start=start, end=end), "-", label)
                        for start, end, label in self.rows)
    output = SimpleNamespace(
        speaker_diarization=Annotation([(0., 3., "a"), (2., 4., "b")]),
        # The exclusive result can have a different first-appearance order.
        exclusive_speaker_diarization=Annotation([(0., 2., "b"), (2., 4., "a")]),
    )
    labels = {}
    original = _speaker_turns(output, label_map=labels)
    exclusive = _speaker_turns(output, exclusive=True, label_map=labels)
    assert all(turn["overlap"] for turn in original)
    assert all(not turn["overlap"] for turn in exclusive)
    assert original[0]["cluster_id"] == "a"
    assert original[0]["speaker_id"] == exclusive[1]["speaker_id"]
    assert original[1]["speaker_id"] == exclusive[0]["speaker_id"]
    proposal = attribute_segments([{"start": 0, "end": 1}], exclusive)
    assert proposal[0]["speaker_id"] == "Speaker 2"


def test_optional_runtime_is_offline_and_disables_usage_telemetry_before_import(tmp_path, monkeypatch):
    import builtins
    import os
    import pytest
    from voice_studio.diarization import diarize
    source = tmp_path / 'media.wav'
    source.write_bytes(b'fixture')
    model = tmp_path / 'model'
    model.mkdir()
    (model / 'config.yaml').write_text('fixture')
    monkeypatch.setenv('PYANNOTE_METRICS_ENABLED', '1')
    monkeypatch.setenv('HF_HUB_OFFLINE', '0')
    monkeypatch.setenv('HF_HUB_DISABLE_TELEMETRY', '0')
    original = builtins.__import__
    attempted = []
    def check_import(name, *args, **kwargs):
        if name == 'pyannote.audio':
            attempted.append(name)
            assert os.environ['PYANNOTE_METRICS_ENABLED'] == '0'
            assert os.environ['HF_HUB_DISABLE_TELEMETRY'] == '1'
            assert os.environ['HF_HUB_OFFLINE'] == '1'
            raise ImportError('model-free fixture')
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', check_import)
    with pytest.raises(RuntimeError, match='uv sync --extra diarization'):
        diarize(source, model)
    assert attempted == ['pyannote.audio']
