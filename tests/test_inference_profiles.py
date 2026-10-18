from pathlib import Path

import pytest

from voice_studio.pipeline import _resolve_profile_threshold
from voice_studio.profiles import (
    DEFAULT_PROFILE_KEY,
    INFERENCE_PROFILES,
    get_inference_profile,
)
from voice_studio.ui import PROFILE_CHOICES


def test_profiles_expose_fast_and_accurate_modes():
    assert DEFAULT_PROFILE_KEY == "fast"
    assert list(INFERENCE_PROFILES) == ["fast", "accurate"]

    fast = INFERENCE_PROFILES["fast"]
    accurate = INFERENCE_PROFILES["accurate"]

    assert "campplus" in fast.model_filename
    assert "eres2netv2" in accurate.model_filename
    assert accurate.model_size > fast.model_size
    assert accurate.model_path.name == accurate.model_filename
    assert fast.model_path.name == fast.model_filename
    assert accurate.model_path.parent != fast.model_path.parent
    assert accurate.model_path.parent.parent == fast.model_path.parent.parent


def test_profile_lookup_rejects_unknown_key():
    with pytest.raises(ValueError, match="Invalid inference profile"):
        get_inference_profile("maximum")


def test_profile_threshold_can_use_default_or_explicit_override():
    profile, threshold = _resolve_profile_threshold("accurate", None)
    assert profile.key == "accurate"
    assert threshold == profile.default_threshold

    profile, threshold = _resolve_profile_threshold("accurate", 0.67)
    assert profile.key == "accurate"
    assert threshold == 0.67


def test_desktop_profile_choices_match_registry():
    assert PROFILE_CHOICES == [
        (profile.label, profile.key)
        for profile in INFERENCE_PROFILES.values()
    ]
