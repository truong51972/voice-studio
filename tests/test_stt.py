from types import SimpleNamespace
import numpy as np
import pytest

from voice_studio.stt import SAMPLE_RATE, STTOptions, _read_chunk, transcribe

def test_bounded_reader_accepts_short_reads():
    class Stream:
        def __init__(self):
            self.payload = np.ones(5, dtype="<f4").tobytes()
        def read(self, n):
            chunk, self.payload = self.payload[:3], self.payload[3:]
            return chunk
    arr = _read_chunk(Stream(), 5)
    assert len(arr) == 5
    assert np.all(arr == 1)

def test_60_min_offsets_with_fake_engine_do_not_hold_all_chunks():
    calls = []
    class FakeWhisper:
        def transcribe(self, chunk, **kwargs):
            calls.append((len(chunk), kwargs))
            return iter([SimpleNamespace(start=.5, end=1.5, text=" Xin chào ", words=None)]), SimpleNamespace(language="vi")
    def stream():
        for i in range(122):  # 61 minutes at 30s/chunk
            yield i * 30.0, np.full(SAMPLE_RATE * 30, .1, dtype=np.float32)
    result = transcribe(
        "fixture.m4a", STTOptions(), engine=FakeWhisper(), chunks=stream()
    )
    assert result["duration"] == 3660
    assert len(result["segments"]) == 122
    assert result["segments"][0]["start"] == .5
    assert result["segments"][-1]["start"] == 3630.5
    assert max(x[0] for x in calls) == SAMPLE_RATE * 30
    assert all(c[1]["vad_filter"] is True for c in calls)

def test_silent_chunks_do_not_call_inference():
    class FailIfCalled:
        def transcribe(self, *_args, **_kwargs):
            raise AssertionError("Do not hallucinate silent audio")
    result = transcribe(
        "silence.wav", STTOptions(language="en", vad=False),
        engine=FailIfCalled(),
        chunks=[(0., np.zeros(SAMPLE_RATE * 5, dtype=np.float32))]
    )
    assert result["segments"] == []
    assert result["duration"] == 5

def test_option_controls_are_validated():
    assert STTOptions(language="vi", vad=False, word_timestamps=True).vad is False
    assert STTOptions().beam_size == 5
    with pytest.raises(ValueError, match="Beam size"):
        STTOptions(beam_size=0)
    with pytest.raises(ValueError):
        STTOptions(language="xx")
    with pytest.raises(ValueError):
        STTOptions(chunk_seconds=3600)
    with pytest.raises(ValueError):
        STTOptions(device="tpu")
