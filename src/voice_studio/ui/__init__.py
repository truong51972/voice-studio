from __future__ import annotations

"""Public desktop UI API; the package preserves the former ui.py import paths."""

from .constants import DEFAULT_REFERENCE_SPEAKERS, MAX_REFERENCE_SPEAKERS
from .main_window import MainWindow, build_app, create_application
from .panels.reference import ReferenceInput
from .theme import APP_STYLESHEET
from .timecode import _fmt_time, _parse_timecode
from .widgets.media_player import DetectionOverlay, PreviewVideoWidget
from .widgets.similarity_plot import SimilarityPlotWidget
from .widgets.timeline import EditorTimelineWidget
from .workers import AnalysisWorker

__all__ = [
    "MainWindow", "build_app", "create_application",
    "DEFAULT_REFERENCE_SPEAKERS", "MAX_REFERENCE_SPEAKERS",
    "ReferenceInput", "DetectionOverlay", "PreviewVideoWidget",
    "SimilarityPlotWidget", "EditorTimelineWidget", "AnalysisWorker",
    "APP_STYLESHEET",
]
