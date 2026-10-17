"""Optional anonymous diarization inspector; no implicit network/model download."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QFileDialog, QHeaderView, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ...task_runtime import TaskManager, TaskRequest


class DiarizationPanel(QWidget):
    startRequested = Signal()
    seekRequested = Signal(float)
    turnsReady = Signal(object)

    def __init__(self, parent=None, *, session=None):
        super().__init__(parent)
        self.session = session
        self._manager = TaskManager(cpu_concurrency=1) if session is None else None
        self._job_id = None
        self._source: str | None = None
        self.output: dict | None = None
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Optional local Community-1 · anonymous speaker clustering"))
        choose = QHBoxLayout()
        self.model_folder = QLineEdit()
        self.model_folder.setPlaceholderText("Local Community-1 directory (config.yaml)")
        browse = QPushButton("Browse")
        browse.clicked.connect(self._browse)
        choose.addWidget(self.model_folder, 1)
        choose.addWidget(browse)
        layout.addLayout(choose)
        controls = QHBoxLayout()
        self.run_button = QPushButton("Analyze speakers")
        self.run_button.clicked.connect(self.start)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.cancel)
        self.cancel_button.setEnabled(False)
        self.apply_button = QPushButton("Apply to transcript")
        self.apply_button.clicked.connect(self._apply)
        self.apply_button.setEnabled(False)
        controls.addWidget(self.run_button)
        controls.addWidget(self.cancel_button)
        controls.addWidget(self.apply_button)
        layout.addLayout(controls)
        self.status = QLabel("No verified identity; overlaps require manual review.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Start", "End", "Anonymous", "Status"])
        self.table.horizontalHeader().setStretchLastSection(True)
        for column in (0, 1, 3):
            self.table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.cellClicked.connect(self._seek)
        layout.addWidget(self.table)
        self._timer = QTimer(self)
        self._timer.setInterval(150)
        self._timer.timeout.connect(self._poll)

    def set_media(self, source: str | None) -> None:
        if self._source == source:
            return
        if self.session is None:
            self.cancel()
        self._source = source
        self.output = None
        self.table.setRowCount(0)
        self.apply_button.setEnabled(False)

    def _browse(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Community-1 local model directory")
        if path:
            self.model_folder.setText(path)

    def start(self) -> None:
        if self.session is not None:
            self.startRequested.emit()
            return
        if self._job_id is not None:
            return
        if not self._source or not Path(self._source).is_file():
            self.status.setText("Open a media file first.")
            return
        model_dir = Path(self.model_folder.text().strip())
        if not model_dir.is_dir() or not (model_dir / "config.yaml").is_file():
            self.status.setText("Choose a complete locally installed Community-1 folder.")
            return
        self._job_id = self._manager.submit(TaskRequest(
            kind="diarization",
            inputs={"target_path": self._source, "model_directory": str(model_dir)},
        ))
        self._manager.poll()
        self.run_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.status.setText("Analyzing locally…")
        self._timer.start()

    def _poll(self) -> None:
        if self._job_id is None:
            return
        self._manager.poll()
        job = self._manager.snapshot(self._job_id)
        if job.state == "completed":
            try:
                self._show(self._manager.result(self._job_id))
            except Exception as exc:
                self.status.setText(f"Failed to read diarization: {exc}")
            self._finish()
        elif job.state == "failed":
            self.status.setText(job.error or "Diarization process failed")
            self._finish()

    def _show(self, result: dict) -> None:
        self.output = result
        project = self.session.project if self.session is not None else None
        names = {s.id: project.speaker(s.id).name for s in project.speakers} if project else {}
        self.table.setRowCount(len(result["turns"]))
        for row, item in enumerate(result["turns"]):
            values = (
                f"{item['start']:.1f}s", f"{item['end']:.1f}s",
                names.get(item["speaker_id"], item["speaker_id"]), "Overlap" if item["overlap"] else "Anonymous",
            )
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(value))
        self.apply_button.setEnabled(True)
        self.status.setText(
            f"{len(result['speakers'])} anonymous clusters; verify manually."
        )

    def _apply(self) -> None:
        if self.output:
            self.turnsReady.emit(self.output.get("exclusive_turns", self.output["turns"]))

    def _seek(self, row: int, _column: int) -> None:
        if self.output and row < len(self.output["turns"]):
            self.seekRequested.emit(float(self.output["turns"][row]["start"]))

    def cancel(self) -> None:
        if self.session is not None:
            self.session.cancel()
            return
        if self._job_id:
            self._manager.cancel(self._job_id)
            self._finish()
            self.status.setText("Diarization cancelled.")

    def _finish(self) -> None:
        self._timer.stop()
        if self._job_id:
            self._manager.acknowledge(self._job_id)
        self._job_id = None
        self.run_button.setEnabled(True)
        self.cancel_button.setEnabled(False)

    def closeEvent(self, event) -> None:
        if self.session is None:
            self.cancel()
        if self._manager is not None:
            self._manager.close()
        super().closeEvent(event)
