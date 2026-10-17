"""Qt project inspector for ordered batch jobs and reviewed results."""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from ...model_registry import get_model, preflight
from ...projects import ProjectStore
from ...stt import STTOptions
from ...task_runtime import TaskManager, TaskRequest


class ProjectsPanel(QWidget):
    openRequested = Signal(str, object)

    def __init__(self, stt_panel, parent=None):
        super().__init__(parent)
        self.stt_panel = stt_panel
        self.project: ProjectStore | None = None
        self.active_id: str | None = None
        self._manager = TaskManager(cpu_concurrency=1)
        self._jobs: dict[str, str] = {}
        layout = QVBoxLayout(self)
        buttons = QHBoxLayout()
        for label, callback in (
            ("Open project", self._open),
            ("Add media", self._add),
            ("Relink", self._relink),
            ("Run pending", self._run),
            ("Export", self._export),
        ):
            button = QPushButton(label)
            button.clicked.connect(callback)
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.status = QLabel("Choose a project folder; files remain local.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Media", "Status", "Duration"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.cellDoubleClicked.connect(self._select)
        layout.addWidget(self.table, 1)
        self._timer = QTimer(self)
        self._timer.setInterval(150)
        self._timer.timeout.connect(self._poll)

    def _open(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Open/create local project folder")
        if folder:
            self._open_folder(folder)

    def _open_folder(self, folder: str) -> None:
        if self._jobs:
            self.status.setText("Finish/cancel batch jobs before switching projects.")
            return
        self.project = ProjectStore(Path(folder))
        self.active_id = None
        self._refresh()

    def _add(self) -> None:
        if self.project is None or self._jobs:
            self.status.setText("Open a project first and finish current jobs.")
            return
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Import audio/video", "",
            "Media (*.m4a *.mp3 *.wav *.flac *.ogg *.mp4 *.mkv *.mov *.avi *.webm)",
        )
        if paths:
            self.project.add(paths)
            self._refresh()

    def _selected_item(self):
        if self.project is None or self.table.currentRow() < 0:
            return None
        row = self.table.currentRow()
        return self.project.items[row] if row < len(self.project.items) else None

    def _relink(self) -> None:
        item = self._selected_item()
        if item is None or self.project is None:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Relink source media")
        if path:
            self.project.relink(item.id, path)
            self._refresh()

    def _options(self) -> dict:
        return asdict(STTOptions(
            model_id=str(self.stt_panel.model.currentData()),
            language=str(self.stt_panel.language.currentData()),
            vad=self.stt_panel.vad.isChecked(),
            word_timestamps=self.stt_panel.words.isChecked(),
        ))

    def _run(self) -> None:
        if self.project is None or self._jobs:
            self.status.setText("Open project / wait for current batch.")
            return
        options = self._options()
        blocked = preflight(get_model(options["model_id"]), device="cpu")
        if blocked:
            self.status.setText("; ".join(blocked))
            return
        for item in self.project.items:
            if not self.project.should_run(item, options):
                continue
            self.project.begin(item.id, options)
            identifier = self._manager.submit(TaskRequest(
                kind="stt", inputs={"target_path": item.source, "options": options},
            ))
            self._jobs[identifier] = item.id
        if not self._jobs:
            self.status.setText("No new jobs: all unaffected results are cached.")
            return
        self._manager.poll()
        self._timer.start()
        self.status.setText(f"Queued {len(self._jobs)} files (sequential).")
        self._refresh()

    def _poll(self) -> None:
        self._manager.poll()
        for job_id, item_id in list(self._jobs.items()):
            state = self._manager.snapshot(job_id)
            if state.state not in ("completed", "failed", "cancelled"):
                continue
            try:
                if state.state == "completed":
                    self.project.complete(item_id, self._manager.result(job_id))
                else:
                    self.project.fail(item_id, state.error or "Cancelled")
            except Exception as exc:
                self.project.fail(item_id, str(exc))
            self._manager.acknowledge(job_id)
            del self._jobs[job_id]
            self._refresh()
        if not self._jobs:
            self._timer.stop()
            self.status.setText("Batch complete. Double-click a row to review.")

    def _refresh(self) -> None:
        if self.project is None:
            return
        self.table.setRowCount(len(self.project.items))
        for row, item in enumerate(self.project.items):
            values = (
                Path(item.source).name, item.status,
                f"{item.duration:.1f}s" if item.duration is not None else "",
            )
            for col, value in enumerate(values):
                self.table.setItem(row, col, QTableWidgetItem(value))
        self.status.setText(f"{self.project.name} · {len(self.project.items)} files")

    def _select(self, row: int, _column: int) -> None:
        if self.project is None or row >= len(self.project.items):
            return
        item = self.project.items[row]
        if item.status != "completed":
            self.status.setText(item.error or "File is not yet processed.")
            return
        self.active_id = item.id
        self.openRequested.emit(item.source, self.project.review(item.id))

    def save_active_review(self, document) -> None:
        if self.project is None or self.active_id is None or document is None:
            return
        item = self.project.get(self.active_id)
        if Path(document.raw_metadata.get("source", "")).resolve() != Path(item.source).resolve():
            return
        self.project.save_review(self.active_id, document)

    def _export(self) -> None:
        if self.project is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export combined transcript", "",
            "Markdown (*.md);;Plain text (*.txt)",
        )
        if not path:
            return
        kind = "txt" if Path(path).suffix.lower() == ".txt" else "md"
        if not Path(path).suffix:
            path += "." + kind
        Path(path).write_text(self.project.combined_export(kind), encoding="utf-8")
        self.status.setText(f"Exported: {Path(path).name}")

    def closeEvent(self, event) -> None:
        self._timer.stop()
        self._manager.close()
        super().closeEvent(event)
