"""Reusable PySide6-free contracts for media and model results."""

from .contracts import (AnalysisResult, MediaAsset, ModelMetadata, RunMetadata,
                        Segment, SpeakerTurn, TranscriptCorrection, TranscriptSegment)

__all__ = ["AnalysisResult", "MediaAsset", "ModelMetadata", "RunMetadata",
           "Segment", "SpeakerTurn", "TranscriptCorrection", "TranscriptSegment"]
