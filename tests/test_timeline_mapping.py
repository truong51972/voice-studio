import math

import pytest

from voice_studio.domain.timeline import TimelineClip, TimelineMap


def test_mapping_trimmed_clips_and_shared_boundaries():
    a = TimelineClip("clip-a", "media-a", 10., 20.)
    b = TimelineClip("clip-b", "media-b", 5., 12.)
    timeline = TimelineMap([a, b], {"media-a": 30., "media-b": 15.})
    assert timeline.duration == 17.
    assert timeline.project_to_source(0.) == (a, 10.)
    assert timeline.project_to_source(9.5) == (a, 19.5)
    assert timeline.project_to_source(10.) == (b, 5.)
    assert timeline.project_to_source(17.) == (b, 12.)
    assert timeline.source_to_project(b.id, 8.) == 13.
    reordered = TimelineMap([b, a], timeline.durations)
    assert reordered.source_to_project(a.id, 15.) == 12.
    assert (a.source_in, a.source_out) == (10., 20.)


@pytest.mark.parametrize("seconds", [-1., 18., math.inf, math.nan])
def test_out_of_bounds_project_time_is_rejected(seconds):
    timeline = TimelineMap([TimelineClip("c", "m")], {"m": 17.})
    with pytest.raises(ValueError):
        timeline.project_to_source(seconds)


def test_invalid_source_boundaries_and_missing_duration_are_rejected():
    with pytest.raises(ValueError):
        TimelineClip("c", "m", 3., 2.)
    with pytest.raises(ValueError, match="duration"):
        TimelineMap([TimelineClip("c", "m", 0., 21.)], {"m": 20.})
    with pytest.raises(ValueError, match="Probe source duration"):
        TimelineMap([TimelineClip("c", "m")], {"m": None})
    with pytest.raises(ValueError, match="unknown media"):
        TimelineMap([TimelineClip("c", "missing")], {})
    with pytest.raises(ValueError, match="empty"):
        TimelineMap([], {}).project_to_source(0.)
    timeline = TimelineMap([TimelineClip("c", "m", 2., 4.)], {"m": 5.})
    with pytest.raises(ValueError):
        timeline.source_to_project("c", 1.)


def test_fractional_clip_endpoints_roundtrip():
    clips = [TimelineClip("a", "m", .1, .3), TimelineClip("b", "m", .2, .9)]
    timeline = TimelineMap(clips, {"m": 1.})
    clip, source = timeline.project_to_source(timeline.duration)
    assert clip.id == "b"
    assert source == pytest.approx(.9)
    assert timeline.source_to_project(clip.id, source) == pytest.approx(timeline.duration)
