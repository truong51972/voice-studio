from __future__ import annotations

"""Compatibility facade for the modular desktop UI package.

The v0.1.0 editor was a single `ui.py` module. Keep its exported constants,
widgets and constructors reachable from `voice_studio.ui` after the split.
"""

from ..config import DEFAULT_THRESHOLD
from ..pipeline import AnalysisBundle
from ..profiles import DEFAULT_PROFILE_KEY, INFERENCE_PROFILES, get_inference_profile
from .constants import (
    DEFAULT_REFERENCE_SPEAKERS, MAX_REFERENCE_SPEAKERS, PROFILE_CHOICES,
    SCENARIOS, SEGMENT_HEADERS,
)
from .main_window import MainWindow, build_app, create_application
from .panels.reference import ReferenceInput
from .resources import _resource_path
from .theme import APP_STYLESHEET, TRACK_COLORS
from .timecode import _fmt_time, _parse_timecode
from .widgets.media_player import DetectionOverlay, PreviewVideoWidget
from .widgets.similarity_plot import SimilarityPlotWidget
from .widgets.timeline import EditorTimelineWidget
from .workers import AnalysisWorker

__all__ = [
    "MainWindow", "build_app", "create_application",
    "DEFAULT_REFERENCE_SPEAKERS", "MAX_REFERENCE_SPEAKERS",
    "DEFAULT_THRESHOLD", "DEFAULT_PROFILE_KEY", "INFERENCE_PROFILES",
    "get_inference_profile", "AnalysisBundle",
    "PROFILE_CHOICES", "SCENARIOS", "SEGMENT_HEADERS", "TRACK_COLORS",
    "ReferenceInput", "DetectionOverlay", "PreviewVideoWidget",
    "SimilarityPlotWidget", "EditorTimelineWidget", "AnalysisWorker",
    "APP_STYLESHEET",
]
