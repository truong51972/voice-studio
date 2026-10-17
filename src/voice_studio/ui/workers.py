from __future__ import annotations

"""Locator worker boundary; issue #5 will add subprocess cancellation and queueing."""

from PySide6.QtCore import QThread, Signal

from ..service import LocatorService


class AnalysisWorker(QThread):
    completed = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        references,
        target_audio,
        target_video,
        threshold: float,
        scenario: str,
        profile_key: str,
    ):
        super().__init__()
        self._references = references
        self._target_audio = target_audio
        self._target_video = target_video
        self._threshold = threshold
        self._scenario = scenario
        self._profile_key = profile_key

    def run(self) -> None:
        try:
            bundle, resolved_threshold = LocatorService().analyze(
                self._references,
                self._target_audio,
                self._target_video,
                self._threshold,
                profile_key=self._profile_key,
            )
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.completed.emit(
            (bundle, resolved_threshold, self._scenario, self._profile_key)
        )
