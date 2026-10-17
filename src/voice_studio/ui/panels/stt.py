"""STT inspector: streaming local inference, transcript rows, shared seek clock."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QLabel, QMessageBox,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ...model_registry import descriptors, get_model, preflight
from ...task_runtime import TaskManager, TaskRequest
from ..timecode import _fmt_time


class STTPanel(QWidget):
    seekRequested = Signal(float)
    resultReady = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._manager = TaskManager(cpu_concurrency=1)
        self._job_id: str | None = None
        self._source: str | None = None
        self.raw_result: dict | None = None
        layout = QVBoxLayout(self)
        settings = QFormLayout()
        self.model = QComboBox()
        for descriptor in descriptors("stt"):
            self.model.addItem(descriptor.label, descriptor.id)
        settings.addRow("Model", self.model)
        self.language = QComboBox()
        for label, value in (("Auto detect", "auto"), ("Vietnamese", "vi"), ("English", "en")):
            self.language.addItem(label, value)
        settings.addRow("Language", self.language)
        self.vad = QCheckBox("Speech filtering (VAD)")
        self.vad.setChecked(True)
        self.words = QCheckBox("Word timestamps")
        settings.addRow(self.vad)
        settings.addRow(self.words)
        layout.addLayout(settings)
        commands = QHBoxLayout()
        self.run_button = QPushButton("Transcribe")
        self.run_button.clicked.connect(self.start)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel)
        commands.addWidget(self.run_button)
        commands.addWidget(self.cancel_button)
        layout.addLayout(commands)
        self.status = QLabel("Select local media and install a model in Model Manager.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Start", "End", "Text"])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setColumnWidth(0, 67)
        self.table.setColumnWidth(1, 67)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.cellClicked.connect(self._seek)
        layout.addWidget(self.table, 1)
        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._poll)

    def set_media(self, source: str | None) -> None:
        if source == self._source:
            return
        self.cancel()
        self._source = source
        self.raw_result = None
        self.table.setRowCount(0)

    def start(self) -> None:
        if self._job_id is not None:
            return
        if not self._source or not Path(self._source).is_file():
            self.status.setText("Open a local audio/video file first.")
            return
        model_id = str(self.model.currentData())
        blockers = preflight(get_model(model_id), device="cpu")
        if blockers:
            self.status.setText("; ".join(blockers) + " · Open Models to install.")
            return
        from ...stt import STTOptions
        from dataclasses import asdict
        options = asdict(STTOptions(
            model_id=model_id, language=str(self.language.currentData()),
            vad=self.vad.isChecked(), word_timestamps=self.words.isChecked(),
        ))
        self._job_id = self._manager.submit(TaskRequest(
            kind="stt", inputs={"target_path": self._source, "options": options},
        ))
        self._manager.poll()
        self.run_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.status.setText("Starting offline STT subprocess…")
        self._timer.start()

    def _poll(self) -> None:
        if self._job_id is None:
            return
        self._manager.poll()
        state = self._manager.snapshot(self._job_id)
        self.status.setText(state.stage)
        if state.state == "completed":
            try:
                result = self._manager.result(self._job_id)
                self._show(result)
            except Exception as exc:
                self.status.setText(f"Failed to load transcript: {exc}")
            finally:
                self._finish()
        elif state.state == "failed":
            self.status.setText(state.error or "STT worker crashed")
            self._finish()

    def _show(self, result: dict) -> None:
        self.raw_result = result
        segments = result["segments"]
        self.table.setRowCount(len(segments))
        for i, segment in enumerate(segments):
            for col, value in enumerate((
                _fmt_time(segment["start"]),
                _fmt_time(segment["end"]), segment["text"],
            )):
                self.table.setItem(i, col, QTableWidgetItem(str(value)))
        self.status.setText(f"{len(segments)} transcript segments · {result['duration']:.1f}s")
        self.resultReady.emit(result)

    def _seek(self, row: int, _column: int) -> None:
        if self.raw_result is not None and row < len(self.raw_result["segments"]):
            self.seekRequested.emit(float(self.raw_result["segments"][row]["start"]))

    def cancel(self) -> None:
        if self._job_id:
            self._manager.cancel(self._job_id)
            self.status.setText("STT cancelled.")
            self._finish()

    def _finish(self) -> None:
        self._timer.stop()
        if self._job_id:
            self._manager.acknowledge(self._job_id)
        self._job_id = None
        self.run_button.setEnabled(True)
        self.cancel_button.setEnabled(False)

    def closeEvent(self, event) -> None:
        self.cancel()
        self._manager.close()
        super().closeEvent(event)
