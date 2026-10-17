from voice_studio.localization import WindowScore, merge_matches


def test_merge_positive_windows():
    scores = [
        WindowScore(0.0, 2.5, 1.25, 0.20, True),
        WindowScore(0.5, 3.0, 1.75, 0.70, True),
        WindowScore(1.0, 3.5, 2.25, 0.75, True),
        WindowScore(4.0, 6.5, 5.25, 0.30, True),
    ]
    segments = merge_matches(scores, 0.60, min_duration_seconds=1.0)
    assert len(segments) == 1
    assert segments[0].start == 0.5
    assert segments[0].end == 3.5
