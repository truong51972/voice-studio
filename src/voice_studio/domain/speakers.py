"""Project identities and source-anchored references; no Qt or model imports."""
from dataclasses import dataclass, field
from math import isfinite
import heapq


@dataclass
class ProjectSpeaker:
    id: str
    name: str
    color: str = "#36c5d8"
    merged_into: str | None = None


@dataclass
class ReferenceRegion:
    id: str
    speaker_id: str
    media_id: str
    start: float
    end: float
    fingerprint: str
    model_revision: str = ""
    state: str = "pending"
    error: str | None = None

    def validate(self, duration: float | None) -> None:
        if duration is None or not all(isfinite(x) for x in (self.start, self.end, duration)):
            raise ValueError("Probe source duration before selecting a reference")
        if not 0 <= self.start < self.end <= duration:
            raise ValueError("Reference must lie inside its source media")


@dataclass
class AnalysisRecord:
    id: str
    media_id: str
    task: str
    fingerprint: str
    settings: dict = field(default_factory=dict)
    state: str = "queued"
    error: str | None = None


def has_overlapping_voices(turns: list[dict], start: float, end: float) -> bool:
    """Sweep only intersecting turns; touching boundaries and same-speaker tracks are safe."""
    intervals = sorted((max(start, t['start']), min(end, t['end']), t['speaker_id'])
                       for t in turns if t['end'] > start and t['start'] < end)
    active, counts = [], {}
    for left, right, speaker in intervals:
        while active and active[0][0] <= left:
            _, expired = heapq.heappop(active)
            counts[expired] -= 1
            if not counts[expired]:
                del counts[expired]
        if any(other != speaker for other in counts):
            return True
        counts[speaker] = counts.get(speaker, 0) + 1
        heapq.heappush(active, (right, speaker))
    return False
