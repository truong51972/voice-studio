from __future__ import annotations

from pathlib import Path
from typing import TypeAlias

import numpy as np

from .pipeline import AnalysisBundle, _compute_analysis
from .profiles import DEFAULT_PROFILE_KEY, get_inference_profile

AudioInput: TypeAlias = tuple[int, np.ndarray] | str | Path | None


def analyze_bundle(
    references: list[tuple[str, AudioInput]],
    target_audio: AudioInput,
    target_video: str | Path | None,
    threshold: float | None,
    *,
    profile_key: str = DEFAULT_PROFILE_KEY,
) -> tuple[AnalysisBundle, float]:
    """Run the matching core for desktop clients without a web-UI contract."""
    profile = get_inference_profile(profile_key)
    resolved_threshold = profile.default_threshold if threshold is None else float(threshold)
    bundle = _compute_analysis(
        references,
        target_audio,
        target_video,
        resolved_threshold,
        profile_key=profile.key,
    )
    return bundle, resolved_threshold
