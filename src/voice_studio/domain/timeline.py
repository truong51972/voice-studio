"""Sequential source track. Raw inference timestamps never move with clips."""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True, slots=True)
class TimelineClip:
    id: str
    media_id: str
    source_in: float = 0.0
    # None means the full source, including legacy media awaiting a duration probe.
    source_out: float | None = None

    def __post_init__(self):
        if not isfinite(self.source_in) or self.source_in < 0:
            raise ValueError("Clip start must be finite and nonnegative")
        if self.source_out is not None:
            if not isfinite(self.source_out) or self.source_out <= self.source_in:
                raise ValueError("Clip end must be finite and after its start")

    def end(self, duration: float | None) -> float:
        if duration is None or not isfinite(duration) or duration <= 0:
            raise ValueError(f"Probe source duration before mapping media {self.media_id}")
        end = duration if self.source_out is None else self.source_out
        if not self.source_in < end <= duration:
            raise ValueError("Clip interval exceeds source duration")
        return end


def map_time(
    clip: TimelineClip, timeline_start: float, seconds: float,
    duration: float | None, *, to_source: bool,
) -> float:
    """The single project ↔ source conversion, in seconds with inclusive endpoints."""
    end = clip.end(duration)
    if not isfinite(seconds) or not isfinite(timeline_start) or timeline_start < 0:
        raise ValueError("Time must be finite and timeline start nonnegative")
    project_end = timeline_start + (end - clip.source_in)
    lower, upper = ((timeline_start, project_end)
                    if to_source else (clip.source_in, end))
    if not lower <= seconds <= upper:
        raise ValueError("Time is outside the selected clip")
    if to_source:
        return min(end, clip.source_in + (seconds - timeline_start))
    return min(project_end, timeline_start + (seconds - clip.source_in))


class TimelineMap:
    def __init__(self, clips: list[TimelineClip], durations: dict[str, float | None]):
        self.clips = tuple(clips)
        self.durations = dict(durations)
        self.starts: dict[str, float] = {}
        self.duration = 0.0
        for clip in self.clips:
            if clip.id in self.starts:
                raise ValueError("Timeline clip IDs must be unique")
            if clip.media_id not in self.durations:
                raise ValueError("Timeline clip references unknown media")
            self.starts[clip.id] = self.duration
            self.duration += clip.end(self.durations[clip.media_id]) - clip.source_in

    def project_to_source(self, seconds: float) -> tuple[TimelineClip, float]:
        if not isfinite(seconds) or not 0 <= seconds <= self.duration:
            raise ValueError("Time is outside the project timeline")
        for index, clip in enumerate(self.clips):
            # A shared boundary belongs to the following clip; final end is seekable.
            if index + 1 == len(self.clips) or seconds < self.starts[self.clips[index + 1].id]:
                return clip, self._map(clip, seconds, to_source=True)
        raise ValueError("The project timeline is empty")

    def source_to_project(self, clip_id: str, seconds: float) -> float:
        clip = next((clip for clip in self.clips if clip.id == clip_id), None)
        if clip is None:
            raise ValueError("Unknown timeline clip")
        return self._map(clip, seconds, to_source=False)

    def _map(self, clip: TimelineClip, seconds: float, *, to_source: bool) -> float:
        return map_time(clip, self.starts[clip.id], seconds,
                        self.durations[clip.media_id], to_source=to_source)
