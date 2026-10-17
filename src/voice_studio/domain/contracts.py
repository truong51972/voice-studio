from __future__ import annotations

"""UI-independent source-local contracts shared by Locator, STT and diarization.

Times are floating-point seconds relative to each *source media asset*, never
wall-clock timestamps or offsets into a concatenation of recordings.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from math import isfinite
from pathlib import Path
from typing import Literal


MediaKind = Literal["audio", "video"]
AnalysisTask = Literal["locator", "stt", "diarization"]


def _check_interval(start: float, end: float) -> None:
    if not isfinite(start) or not isfinite(end) or start < 0 or end < start:
        raise ValueError("Expected 0 <= start <= end, in finite media-local seconds")


def _check_confidence(value: float | None) -> None:
    if value is not None and (not isfinite(value) or not 0 <= value <= 1):
        raise ValueError("Confidence must be between zero and one, or None")


@dataclass(frozen=True, slots=True)
class MediaAsset:
    """A single local file; duration may be populated after player probing."""

    path: Path
    kind: MediaKind
    duration_seconds: float | None = None

    def __post_init__(self) -> None:
        if self.kind not in ("audio", "video"):
            raise ValueError("Unsupported media kind")
        if not isinstance(self.path, Path):
            object.__setattr__(self, "path", Path(self.path))
        if self.duration_seconds is not None:
            if not isfinite(self.duration_seconds) or self.duration_seconds < 0:
                raise ValueError("Media duration must be a finite nonnegative number")


@dataclass(frozen=True, slots=True)
class Segment:
    start: float
    end: float

    def __post_init__(self) -> None:
        _check_interval(self.start, self.end)


@dataclass(frozen=True, slots=True)
class TranscriptSegment(Segment):
    """Immutable raw engine hypothesis, *not* the user-edited transcript."""

    text: str = ""
    segment_id: str = ""
    speaker_id: str | None = None
    language: str | None = None
    confidence: float | None = None

    def __post_init__(self) -> None:
        Segment.__post_init__(self)
        _check_confidence(self.confidence)


@dataclass(frozen=True, slots=True)
class SpeakerTurn(Segment):
    """Anonymous diarization cluster unless a separate enrollment maps it."""

    speaker_id: str | None = None
    confidence: float | None = None

    def __post_init__(self) -> None:
        Segment.__post_init__(self)
        _check_confidence(self.confidence)


@dataclass(frozen=True, slots=True)
class ModelMetadata:
    model_id: str
    task: AnalysisTask
    engine: str
    version: str | None = None
    # Tuples prevent callers mutating provenance after inference.
    settings: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class RunMetadata:
    run_id: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    parameters: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("Run creation timestamp must be timezone-aware")


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    """A snapshot of raw model results. Editing never mutates this object."""

    media: MediaAsset
    task: AnalysisTask
    segments: tuple[Segment, ...] = ()
    transcript: tuple[TranscriptSegment, ...] = ()
    speaker_turns: tuple[SpeakerTurn, ...] = ()
    model: ModelMetadata | None = None
    run: RunMetadata | None = None

    def __post_init__(self) -> None:
        if self.task not in ("locator", "stt", "diarization"):
            raise ValueError("Unsupported analysis task")
        for sequence in (self.segments, self.transcript, self.speaker_turns):
            if not isinstance(sequence, tuple):
                raise TypeError("Raw result collections must be immutable tuples")
            if self.media.duration_seconds is not None:
                for item in sequence:
                    if item.end > self.media.duration_seconds + 0.001:
                        raise ValueError("Segment exceeds media-local duration")


@dataclass(frozen=True, slots=True)
class TranscriptCorrection:
    """User override stored separately from immutable engine hypotheses."""

    segment_id: str
    corrected_text: str
    speaker_id: str | None = None

    def __post_init__(self) -> None:
        if not self.segment_id:
            raise ValueError("Transcript correction requires a segment ID")
