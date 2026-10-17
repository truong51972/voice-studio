"""STT panel: media-clock synchronized transcription, corrections, exports."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QFileDialog, QFormLayout,
    QHBoxLayout, QInputDialog, QLabel, QPushButton, QLineEdit,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ...model_registry import descriptors, get_model, preflight
from ...task_runtime import TaskManager, TaskRequest
from ...transcript import TranscriptDocument, export_text
from ..timecode import _fmt_time


class STTPanel(QWidget):
    seekRequested = Signal(float)
    resultReady = Signal(object)
    documentChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._manager = TaskManager(cpu_concurrency=1)
        self._job_id: str | None = None
        self._source: str | None = None
        self.raw_result: dict | None = None
        self.document: TranscriptDocument | None = None
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
        self.status = QLabel("Select media and install a model in Model Manager.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search transcript…")
        self.search.textChanged.connect(self._filter)
        layout.addWidget(self.search)
        editor_actions = QHBoxLayout()
        self.speaker_button = QPushButton("Speaker")
        self.speaker_button.clicked.connect(self._speaker)
        self.split_button = QPushButton("Split")
        self.split_button.clicked.connect(self._split)
        self.merge_button = QPushButton("Merge")
        self.merge_button.clicked.connect(self._merge)
        self.reset_button = QPushButton("Revert")
        self.reset_button.clicked.connect(self._reset)
        self.export_button = QPushButton("Export")
        self.export_button.clicked.connect(self._export)
        for button in (
            self.speaker_button, self.split_button, self.merge_button,
            self.reset_button, self.export_button,
        ):
            editor_actions.addWidget(button)
        layout.addLayout(editor_actions)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Start", "End", "Speaker", "Text"])
        self.table.setColumnWidth(0, 62)
        self.table.setColumnWidth(1, 62)
        self.table.setColumnWidth(2, 78)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked)
        self.table.itemChanged.connect(self._edit_text)
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
        self.document = None
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
                self._show(self._manager.result(self._job_id))
            except Exception as exc:
                self.status.setText(f"Failed to load transcript: {exc}")
            finally:
                self._finish()
        elif state.state == "failed":
            self.status.setText(state.error or "STT worker crashed")
            self._finish()

    def _show(self, result: dict) -> None:
        self.raw_result = result
        self.document = TranscriptDocument(result)
        self._render()
        self.status.setText(
            f"{len(self.document.edited)} transcript segments · {result['duration']:.1f}s"
        )
        self.resultReady.emit(result)

    def load_document(self, document: TranscriptDocument) -> None:
        """Restores reviewed project data; #8 saves the serialized document."""
        self.cancel()
        self.document = document
        self.raw_result = {
            **document.raw_metadata,
            "segments": [s.as_dict() for s in document.raw],
        }
        self._render()

    def _render(self) -> None:
        if self.document is None:
            return
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.document.edited))
        for i, s in enumerate(self.document.edited):
            for col, text in enumerate((
                _fmt_time(s.start), _fmt_time(s.end), s.speaker_id or "", s.text,
            )):
                item = QTableWidgetItem(str(text))
                if col != 3:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(i, col, item)
        self.table.blockSignals(False)
        self._filter(self.search.text())

    def _filter(self, text: str) -> None:
        if self.document is None:
            return
        valid = set(self.document.find(text))
        for row in range(self.table.rowCount()):
            self.table.setRowHidden(row, row not in valid)

    def _edit_text(self, item: QTableWidgetItem) -> None:
        if self.document is None or item.column() != 3:
            return
        row = item.row()
        if row < len(self.document.edited):
            self.document.replace(self.document.edited[row].id, text=item.text())
            self.documentChanged.emit()

    def _selected_rows(self) -> list[int]:
        return sorted({i.row() for i in self.table.selectedIndexes()})

    def _speaker(self) -> None:
        if self.document is None:
            return
        rows = self._selected_rows()
        if not rows:
            return
        label, ok = QInputDialog.getText(self, "Speaker label", "Name (blank = unknown)")
        if ok:
            for row in rows:
                self.document.replace(
                    self.document.edited[row].id,
                    speaker_id=label.strip() or None, rename_speaker=True,
                )
            self._render()
            self.documentChanged.emit()

    def _split(self) -> None:
        if self.document is None:
            return
        rows = self._selected_rows()
        if len(rows) != 1:
            self.status.setText("Select exactly one row to split.")
            return
        segment = self.document.edited[rows[0]]
        at, ok = QInputDialog.getDouble(
            self, "Split segment", "Split time (seconds)",
            (segment.start + segment.end) / 2,
            segment.start, segment.end, 3,
        )
        if ok:
            try:
                self.document.split(segment.id, at)
                self._render()
                self.documentChanged.emit()
            except ValueError as exc:
                self.status.setText(str(exc))

    def _merge(self) -> None:
        if self.document is None:
            return
        rows = self._selected_rows()
        if len(rows) != 2 or rows[1] != rows[0] + 1:
            self.status.setText("Select two adjacent rows to merge.")
            return
        first, second = (self.document.edited[i].id for i in rows)
        self.document.merge(first, second)
        self._render()
        self.documentChanged.emit()

    def _reset(self) -> None:
        if self.document:
            self.document.reset()
            self._render()
            self.documentChanged.emit()

    def apply_diarization(self, turns: list[dict]) -> None:
        """Apply suggested anonymous labels to editable view, not raw Whisper output."""
        if self.document is None:
            self.status.setText("Transcribe this media first.")
            return
        from ...diarization import attribute_segments
        source = [entry.as_dict() for entry in self.document.edited]
        proposed = attribute_segments(source, turns)
        for old, new in zip(source, proposed):
            if not old.get("speaker_id") and new.get("speaker_id"):
                self.document.replace(
                    old["id"], speaker_id=new["speaker_id"], rename_speaker=True,
                )
        self._render()
        self.documentChanged.emit()

    def _export(self) -> None:
        if self.document is None:
            self.status.setText("No transcript to export.")
            return
        path, selected = QFileDialog.getSaveFileName(
            self, "Export reviewed transcript", "",
            "Markdown (*.md);;SubRip (*.srt);;Plain text (*.txt);;JSON (*.json)",
        )
        if not path:
            return
        format_name = Path(path).suffix.lstrip(".").lower()
        if format_name not in ("md", "srt", "txt", "json"):
            format_name = "md"
            path += ".md"
        Path(path).write_text(
            export_text(self.document, format_name), encoding="utf-8"
        )
        self.status.setText(f"Exported {Path(path).name}")

    def _seek(self, row: int, _column: int) -> None:
        if self.document is not None and row < len(self.document.edited):
            self.seekRequested.emit(float(self.document.edited[row].start))

    def set_playhead(self, seconds: float) -> None:
        if self.document is None:
            return
        if self.table.state() == QAbstractItemView.State.EditingState:
            return
        for i, segment in enumerate(self.document.edited):
            if segment.start <= seconds < segment.end and not self.table.isRowHidden(i):
                if self.table.currentRow() != i:
                    self.table.selectRow(i)
                break

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
