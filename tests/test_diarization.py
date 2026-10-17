from types import SimpleNamespace
from voice_studio.diarization import _speaker_turns, attribute_segments

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
