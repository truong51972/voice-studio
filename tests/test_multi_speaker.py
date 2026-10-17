import numpy as np

from voice_studio.localization import score_references
from voice_studio.similarity import cosine_similarity_matrix


class CountingEmbedder:
    def __init__(self):
        self.calls = 0

    def compute(self, samples, sample_rate=16_000):
        self.calls += 1
        x = np.asarray(samples, dtype=np.float32)
        # Deterministic two-dimensional test embedding.
        mean = float(np.mean(x)) if x.size else 0.0
        std = float(np.std(x)) if x.size else 0.0
        v = np.array([mean + 1.0, std + 0.5], dtype=np.float32)
        return v / np.linalg.norm(v)


def test_cosine_similarity_matrix_shape_and_identity():
    refs = np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
    targets = np.array([[1.0, 0.0], [0.0, 1.0], [1.0, 1.0]], dtype=np.float32)
    scores = cosine_similarity_matrix(refs, targets)
    assert scores.shape == (2, 3)
    assert scores[0, 0] == 1.0
    assert scores[1, 1] == 1.0


def test_target_windows_are_embedded_once_for_multiple_references():
    sample_rate = 100
    target = np.ones(500, dtype=np.float32)
    references = {
        "a": np.ones(120, dtype=np.float32),
        "b": np.ones(140, dtype=np.float32) * 0.8,
        "c": np.ones(160, dtype=np.float32) * 0.6,
    }
    embedder = CountingEmbedder()

    result = score_references(
        references,
        target,
        embedder,
        sample_rate=sample_rate,
        window_seconds=2.0,
        hop_seconds=1.0,
        min_rms=0.001,
        smoothing_kernel=1,
    )

    # Target 5s, 2s windows, 1s hop => 4 target windows. The optimized path
    # computes 3 reference embeddings + 4 target embeddings = 7 calls total,
    # not 3 * 4 target calls.
    assert set(result) == {"a", "b", "c"}
    assert all(len(scores) == 4 for scores in result.values())
    assert embedder.calls == 7


def test_primary_lane_figure_stays_compact_for_six_speakers():
    from voice_studio.visualization import build_speaker_lanes_figure

    segments = {f"Speaker {i}": [] for i in range(1, 7)}
    fig = build_speaker_lanes_figure(120.0, segments)
    assert fig.layout.height <= 360


def test_primary_lane_figure_contains_baselines_and_detected_segments():
    from voice_studio.localization import MatchSegment
    from voice_studio.visualization import build_speaker_lanes_figure

    segments = {
        "Speaker A": [MatchSegment(2.0, 4.5, 0.71, 0.83)],
        "Speaker B": [],
        "Speaker C": [
            MatchSegment(6.0, 8.0, 0.69, 0.79),
            MatchSegment(10.0, 12.5, 0.74, 0.86),
        ],
    }
    fig = build_speaker_lanes_figure(15.0, segments)

    # 3 quiet baselines + 3 detected segment traces.
    assert len(fig.data) == 6
    assert list(fig.layout.yaxis.ticktext) == ["Speaker A", "Speaker B", "Speaker C"]
    assert tuple(fig.layout.xaxis.range) == (0, 15.0)
    segment_traces = [trace for trace in fig.data if getattr(trace.line, "width", None) == 18]
    assert len(segment_traces) == 3


def test_timeline_placeholder_has_stable_nonzero_layout():
    from voice_studio.visualization import build_timeline_placeholder_figure

    fig = build_timeline_placeholder_figure()
    assert fig.layout.height == 220
    assert len(fig.layout.annotations) == 1
    assert "Timeline" in fig.layout.annotations[0].text
