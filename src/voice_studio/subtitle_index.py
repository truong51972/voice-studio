"""Efficient, source-relative, end-exclusive subtitle lookup.

Builds a non-overlapping event sweep once per review revision; playhead lookup is
O(log n), even with overlapping/split segments or repeated timeline clips.
"""
from __future__ import annotations

from bisect import bisect_right
from heapq import heappush, heappop
from math import isfinite

from .transcript import TranscriptEntry


class SubtitleIndex:
    def __init__(self, entries=()):
        self.times: list[float] = []
        self.active: list[TranscriptEntry | None] = []
        self.set_entries(entries)

    def set_entries(self, entries) -> None:
        events: dict[float, tuple[list, list]] = {}
        entries = list(entries)
        for index, entry in enumerate(entries):
            if (not entry.text.strip() or not isfinite(entry.start) or
                    not isfinite(entry.end) or entry.end <= entry.start):
                continue
            events.setdefault(entry.start, ([], []))[0].append(index)
            events.setdefault(entry.end, ([], []))[1].append(index)
        live: set[int] = set()
        heap: list[tuple[float, float, int]] = []
        self.times, self.active = [], []
        for time in sorted(events):
            starts, ends = events[time]
            for index in ends:
                live.discard(index)
            for index in starts:
                live.add(index)
                entry = entries[index]
                # Latest start wins; ties prefer earliest end, then stable order.
                heappush(heap, (-entry.start, entry.end, index))
            while heap and heap[0][2] not in live:
                heappop(heap)
            self.times.append(time)
            self.active.append(entries[heap[0][2]] if heap else None)

    def at(self, source_seconds: float) -> TranscriptEntry | None:
        if not isfinite(source_seconds) or source_seconds < 0:
            return None
        index = bisect_right(self.times, source_seconds) - 1
        return self.active[index] if index >= 0 else None
