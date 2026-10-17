"""Qt event bridge for the process-isolated TaskManager."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

from ..task_runtime import TaskManager, TaskRequest, reconstruct_locator


class AnalysisWorker(QObject):
    completed = Signal(object)
    failed = Signal(str)
    finished = Signal()
    progress = Signal(str)

    def __init__(
        self, references, target_audio, target_video,
        threshold: float, scenario: str, profile_key: str,
        parent=None,
    ):
        super().__init__(parent)
        self._manager = TaskManager(cpu_concurrency=1)
        self._job_id = None
        source = target_video or target_audio
        if source is None or not isinstance(source, (str, Path)):
            raise ValueError("Locator requires a local media file")
        self._request = TaskRequest(
            kind="locator",
            inputs={
                "references": [[str(n), None if p is None else str(p)] for n, p in references],
                "target_path": str(source),
                "media_kind": "video" if target_video else "audio",
                "threshold": float(threshold),
                "scenario": scenario,
                "profile": profile_key,
            },
        )
        self._timer = QTimer(self)
        self._timer.setInterval(75)
        self._timer.timeout.connect(self._poll)
        self._last_stage = ""

    def start(self) -> None:
        if self.isRunning():
            return
        self._job_id = self._manager.submit(self._request)
        self._manager.poll()
        self._timer.start()

    def isRunning(self) -> bool:  # legacy QThread-shaped public API
        return self._job_id is not None and self._manager.snapshot(self._job_id).state in ("queued", "running")

    def cancel(self) -> None:
        if self._job_id and self.isRunning():
            self._manager.cancel(self._job_id)
            self._finish()

    def _poll(self) -> None:
        if self._job_id is None:
            return
        self._manager.poll()
        state = self._manager.snapshot(self._job_id)
        if state.stage != self._last_stage:
            self._last_stage = state.stage
            self.progress.emit(state.stage)
        if state.state == "completed":
            try:
                payload = self._manager.result(self._job_id)
                bundle = reconstruct_locator(payload)
                self.completed.emit((
                    bundle, payload["threshold"], payload["scenario"], payload["profile"]
                ))
            except Exception as exc:
                self.failed.emit(f"Could not read worker output: {exc}")
            self._finish()
        elif state.state == "failed":
            self.failed.emit(state.error or "Inference worker failed")
            self._finish()

    def _finish(self) -> None:
        self._timer.stop()
        self._manager.close()
        self._job_id = None
        self.finished.emit()
