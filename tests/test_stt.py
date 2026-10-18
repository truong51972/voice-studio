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


def test_out_of_window_and_nonfinite_whisper_segments_do_not_fail_whole_job():
    from voice_studio.stt import _bounded_times

    assert _bounded_times(30.2, 30.8, 30.) is None
    assert _bounded_times(-1., .5, 30.) == (0., .5)
    assert _bounded_times(29.5, 30.8, 30.) == (29.5, 30.)
    assert _bounded_times(float("nan"), 5., 30.) is None
    assert _bounded_times(3., float("inf"), 30.) is None
    assert _bounded_times(4., 2., 30.) is None
    assert _bounded_times(1., 1., 30.) is None

    class Fake:
        def transcribe(self, *_args, **_kwargs):
            raw = [(0., 1.), (30.2, 30.8), (float("nan"), 2.), (4., 3.), (29.5, 30.3)]
            return iter(SimpleNamespace(start=a, end=b, text="speech", words=None)
                        for a, b in raw), SimpleNamespace(language="en")

    result = transcribe("fixture.wav", STTOptions(), engine=Fake(),
                        chunks=[(0., np.ones(SAMPLE_RATE * 30, dtype=np.float32) * .1)])
    assert len(result["segments"]) == 2
    assert result["segments"][-1]["end"] == 30.
    assert result["warning_count"] == 3
    assert any("30.2" in message for message in result["warnings"])


def test_invalid_word_timestamps_do_not_break_subtitle_export():
    class Fake:
        def transcribe(self, *_args, **_kwargs):
            words = [SimpleNamespace(start=.1, end=.3, word="Hello"),
                     SimpleNamespace(start=float("nan"), end=.6, word="bad"),
                     SimpleNamespace(start=40., end=41., word="bad")]
            segment = SimpleNamespace(start=0., end=1., text="Hello", words=words)
            return iter([segment]), SimpleNamespace(language="en")

    result = transcribe("fixture.wav", STTOptions(word_timestamps=True), engine=Fake(),
                        chunks=[(0., np.ones(SAMPLE_RATE * 5, dtype=np.float32) * .1)])
    assert len(result["segments"]) == 1
    assert len(result["segments"][0]["words"]) == 1
    assert result["warning_count"] == 2


def test_checkpoint_restarts_at_last_completed_chunk_not_from_zero(tmp_path):
    from voice_studio.storage import read_json

    checkpoint = tmp_path / "cache" / "stt" / "partial.json"
    chunks = [(0., np.ones(SAMPLE_RATE * 5, dtype=np.float32) * .1),
              (5., np.ones(SAMPLE_RATE * 5, dtype=np.float32) * .1)]
    class Interrupted:
        calls = 0
        def transcribe(self, *_args, **_kwargs):
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError("Interrupted GPU job")
            return iter([SimpleNamespace(start=.5, end=1.5, text="first", words=None)]), SimpleNamespace(language="en")
    broken = Interrupted()
    with pytest.raises(RuntimeError, match="Interrupted GPU"):
        transcribe("fixture.wav", STTOptions(), engine=broken, chunks=chunks,
                   checkpoint_path=checkpoint, total_seconds=10)
    saved = read_json(checkpoint)
    assert saved["processed_seconds"] == 5.
    assert len(saved["segments"]) == 1

    class Resume:
        calls = 0
        def transcribe(self, *_args, **_kwargs):
            self.calls += 1
            return iter([SimpleNamespace(start=.25, end=1., text="second", words=None)]), SimpleNamespace(language="en")
    engine = Resume()
    progress = []
    result = transcribe("fixture.wav", STTOptions(), engine=engine, chunks=chunks,
                        checkpoint_path=checkpoint, total_seconds=10, progress=progress.append)
    assert engine.calls == 1
    assert result["duration"] == 10.
    assert [x["text"] for x in result["segments"]] == ["first", "second"]
    assert result["segments"][1]["start"] == 5.25
    assert any(x["stage"] == "Resuming from saved audio" for x in progress)

    # Different inference options cannot accidentally ingest a prior result.
    changed = Resume()
    rerun = transcribe("fixture.wav", STTOptions(vad=False), engine=changed,
                       chunks=chunks, checkpoint_path=checkpoint)
    assert changed.calls == 2
    assert len(rerun["segments"]) == 2
