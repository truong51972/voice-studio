from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from voice_studio.domain import (
    AnalysisResult, MediaAsset, ModelMetadata, RunMetadata,
    Segment, SpeakerTurn, TranscriptCorrection, TranscriptSegment,
)


def test_media_timebase_is_per_file_and_finite():
    media = MediaAsset(path="session01.m4a", kind="audio", duration_seconds=60.0)
    assert media.path == Path("session01.m4a")
    assert Segment(start=0.0, end=60.0).end == 60.0
    with pytest.raises(ValueError):
        Segment(start=-1.0, end=2.0)
    with pytest.raises(ValueError):
        Segment(start=3.0, end=2.0)
    with pytest.raises(ValueError):
        Segment(start=float("nan"), end=2.0)
    with pytest.raises(ValueError):
        MediaAsset(path="x", kind="audio", duration_seconds=float("inf"))
    with pytest.raises(ValueError):
        MediaAsset(path="x", kind="document")


def test_transcripts_and_speaker_turns_preserve_uncertainty():
    segment = TranscriptSegment(start=1.0, end=2.0, text="Chào bạn", segment_id="a")
    turn = SpeakerTurn(start=1.0, end=2.0, speaker_id=None)
    assert segment.confidence is None and turn.speaker_id is None
    with pytest.raises(ValueError):
        TranscriptSegment(start=1.0, end=2.0, text="x", confidence=1.1)
    with pytest.raises(ValueError):
        SpeakerTurn(start=1.0, end=2.0, confidence=float("nan"))


def test_raw_result_is_frozen_and_corrections_live_separately():
    media = MediaAsset(path="meeting.m4a", kind="audio", duration_seconds=20)
    raw = TranscriptSegment(start=2.0, end=3.0, text="original", segment_id="s1")
    result = AnalysisResult(
        media=media, task="stt", transcript=(raw,),
        model=ModelMetadata(model_id="small", task="stt", engine="whisper"),
        run=RunMetadata(run_id="r1"),
    )
    edit = TranscriptCorrection(segment_id="s1", corrected_text="corrected")
    assert result.transcript[0].text == "original"
    assert edit.corrected_text != result.transcript[0].text
    with pytest.raises(FrozenInstanceError):
        result.transcript = ()
    with pytest.raises(ValueError):
        TranscriptCorrection(segment_id="", corrected_text="x")
    with pytest.raises(TypeError):
        AnalysisResult(media=media, task="stt", transcript=[raw])


def test_result_bounds_and_run_provenance():
    media = MediaAsset(path="a.m4a", kind="audio", duration_seconds=30)
    with pytest.raises(ValueError):
        AnalysisResult(media=media, task="locator", segments=(Segment(20, 31),))
    with pytest.raises(ValueError):
        RunMetadata(run_id="r", created_at=datetime(2026, 1, 1))
    run = RunMetadata(run_id="r", created_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert run.created_at.utcoffset().total_seconds() == 0
    assert replace(Segment(1, 2), end=5).end == 5


def test_domain_has_no_qt_or_gradio_imports():
    source = (Path(__file__).parents[1] / "src/voice_studio/domain/contracts.py").read_text()
    assert "import PySide6" not in source
    assert "from PySide6" not in source
    assert "import gradio" not in source
