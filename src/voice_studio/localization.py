from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol

import numpy as np

from .audio import rms
from .similarity import cosine_similarity, cosine_similarity_matrix, moving_average


class Embedder(Protocol):
    def compute(self, samples: np.ndarray, sample_rate: int = 16_000) -> np.ndarray: ...


@dataclass(frozen=True)
class WindowScore:
    start: float
    end: float
    center: float
    score: float
    has_speech: bool


@dataclass(frozen=True)
class MatchSegment:
    start: float
    end: float
    avg_score: float
    max_score: float


@dataclass(frozen=True)
class EmbeddedWindow:
    start: float
    end: float
    center: float
    has_speech: bool
    embedding: np.ndarray | None


def _iter_windows(samples: np.ndarray, sample_rate: int, window_seconds: float, hop_seconds: float):
    window = max(1, int(round(window_seconds * sample_rate)))
    hop = max(1, int(round(hop_seconds * sample_rate)))
    if samples.size <= window:
        yield 0, samples.size, samples
        return
    for start in range(0, samples.size - window + 1, hop):
        end = start + window
        yield start, end, samples[start:end]
    last_start = samples.size - window
    if last_start > 0 and last_start % hop != 0:
        yield last_start, samples.size, samples[last_start:]


def embed_target_windows(
    target: np.ndarray,
    embedder: Embedder,
    *,
    sample_rate: int = 16_000,
    window_seconds: float = 2.5,
    hop_seconds: float = 0.5,
    min_rms: float = 0.005,
) -> list[EmbeddedWindow]:
    """Encode target windows once, regardless of the number of references."""
    out: list[EmbeddedWindow] = []
    for start_i, end_i, chunk in _iter_windows(target, sample_rate, window_seconds, hop_seconds):
        has_speech = rms(chunk) >= min_rms
        embedding: np.ndarray | None = None
        if has_speech:
            try:
                embedding = embedder.compute(chunk, sample_rate)
            except ValueError:
                # Keep the time window so visual alignment stays stable even if a
                # very short/degenerate chunk cannot produce an embedding.
                embedding = None
                has_speech = False
        start = start_i / sample_rate
        end = end_i / sample_rate
        out.append(EmbeddedWindow(start, end, (start + end) / 2, has_speech, embedding))
    return out


def score_reference_embeddings(
    reference_embeddings: Mapping[str, np.ndarray],
    windows: list[EmbeddedWindow],
    *,
    smoothing_kernel: int = 3,
) -> dict[str, list[WindowScore]]:
    """Score N normalized references against one shared target-window embedding set."""
    keys = list(reference_embeddings)
    if not keys:
        return {}
    if not windows:
        return {key: [] for key in keys}

    valid_indices = [i for i, window in enumerate(windows) if window.embedding is not None]
    raw_matrix = np.zeros((len(keys), len(windows)), dtype=np.float32)

    if valid_indices:
        ref_matrix = np.stack([np.asarray(reference_embeddings[key], dtype=np.float32) for key in keys])
        target_matrix = np.stack([np.asarray(windows[i].embedding, dtype=np.float32) for i in valid_indices])
        sims = cosine_similarity_matrix(ref_matrix, target_matrix)
        raw_matrix[:, valid_indices] = sims

    results: dict[str, list[WindowScore]] = {}
    for row, key in enumerate(keys):
        smoothed = moving_average(raw_matrix[row], smoothing_kernel)
        results[key] = [
            WindowScore(window.start, window.end, window.center, float(smoothed[i]), window.has_speech)
            for i, window in enumerate(windows)
        ]
    return results


def score_references(
    references: Mapping[str, np.ndarray],
    target: np.ndarray,
    embedder: Embedder,
    *,
    sample_rate: int = 16_000,
    window_seconds: float = 2.5,
    hop_seconds: float = 0.5,
    min_rms: float = 0.005,
    smoothing_kernel: int = 3,
) -> dict[str, list[WindowScore]]:
    """Compute reference embeddings + one shared target pass for all speakers."""
    ref_embeddings = {
        key: embedder.compute(samples, sample_rate)
        for key, samples in references.items()
    }
    windows = embed_target_windows(
        target,
        embedder,
        sample_rate=sample_rate,
        window_seconds=window_seconds,
        hop_seconds=hop_seconds,
        min_rms=min_rms,
    )
    return score_reference_embeddings(
        ref_embeddings,
        windows,
        smoothing_kernel=smoothing_kernel,
    )


def score_windows(
    reference: np.ndarray,
    target: np.ndarray,
    embedder: Embedder,
    *,
    sample_rate: int = 16_000,
    window_seconds: float = 2.5,
    hop_seconds: float = 0.5,
    min_rms: float = 0.005,
    smoothing_kernel: int = 3,
) -> list[WindowScore]:
    """Backward-compatible single-reference API used by older callers/tests."""
    return score_references(
        {"reference": reference},
        target,
        embedder,
        sample_rate=sample_rate,
        window_seconds=window_seconds,
        hop_seconds=hop_seconds,
        min_rms=min_rms,
        smoothing_kernel=smoothing_kernel,
    )["reference"]


def merge_matches(
    scores: list[WindowScore],
    threshold: float,
    *,
    max_gap_seconds: float = 0.75,
    min_duration_seconds: float = 1.0,
) -> list[MatchSegment]:
    positives = [x for x in scores if x.has_speech and x.score >= threshold]
    if not positives:
        return []

    groups: list[list[WindowScore]] = [[positives[0]]]
    for item in positives[1:]:
        prev = groups[-1][-1]
        if item.start - prev.end <= max_gap_seconds:
            groups[-1].append(item)
        else:
            groups.append([item])

    out: list[MatchSegment] = []
    for group in groups:
        start = group[0].start
        end = group[-1].end
        if end - start < min_duration_seconds:
            continue
        values = [x.score for x in group]
        out.append(MatchSegment(start, end, float(np.mean(values)), float(np.max(values))))
    return out
