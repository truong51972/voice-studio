from __future__ import annotations

from pathlib import Path
from typing import Sequence

from .audio import AudioInput

from .pipeline import AnalysisBundle, _compute_analysis
from .profiles import DEFAULT_PROFILE_KEY, get_inference_profile


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


class LocatorService:
    """Qt-independent adapter exposing the established Locator inference contract.

    The existing `analyze_bundle` remains available for compatibility. Workers
    consume this interface without importing or owning any UI widgets.
    """

    def analyze(
        self,
        references: Sequence[tuple[str, AudioInput]],
        target_audio: AudioInput,
        target_video: str | Path | None,
        threshold: float | None,
        *,
        profile_key: str = DEFAULT_PROFILE_KEY,
    ) -> tuple[AnalysisBundle, float]:
        return analyze_bundle(
            list(references), target_audio, target_video, threshold,
            profile_key=profile_key,
        )
