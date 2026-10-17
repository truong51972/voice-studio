"""STT panel: media-clock synchronized transcription, corrections, exports."""
from __future__ import annotations

from pathlib import Path
import os

from PySide6.QtCore import Qt, QTimer, Signal, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemDelegate, QAbstractItemView, QCheckBox, QComboBox, QFileDialog, QFormLayout,
    QHBoxLayout, QInputDialog, QLabel, QPushButton, QLineEdit,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ...model_registry import descriptors, get_model, preflight
from ...task_runtime import TaskManager, TaskRequest
from ...transcript import TranscriptDocument, export_text
from ..timecode import _fmt_time


class STTPanel(QWidget):
    startRequested = Signal()
    editingStarted = Signal()
    seekRequested = Signal(float)
    resultReady = Signal(object)
    documentChanged = Signal()
    modelsRequested = Signal(str)

    def __init__(self, parent=None, *, session=None):
        super().__init__(parent)
        self.session = session
        self._manager = TaskManager(cpu_concurrency=1) if session is None else None
        self._job_id: str | None = None
        self._source: str | None = None
        self.raw_result: dict | None = None
        self.document: TranscriptDocument | None = None
        self.speaker_names = {}
        self.export_range = None
        self.last_export_path: Path | None = None
        self.before_export = lambda: None
        layout = QVBoxLayout(self)
        settings = QFormLayout()
        self.model = QComboBox()
        for descriptor in descriptors("stt"):
            self.model.addItem(descriptor.label, descriptor.id)
        from ...model_service import ModelService
        self.model.setCurrentIndex(max(0, self.model.findData(ModelService().default_id("stt"))))
        settings.addRow("Model", self.model)
        self.device = QComboBox()
        self.device.addItem("Auto · GPU if verified", "auto")
        self.device.addItem("NVIDIA CUDA", "cuda")
        self.device.addItem("CPU", "cpu")
        settings.addRow("Device", self.device)
        self.gpu_precision = QComboBox()
        self.gpu_precision.addItem("FP16 · fast", "float16")
        self.gpu_precision.addItem("INT8 + FP16 · lower VRAM", "int8_float16")
        settings.addRow("GPU precision", self.gpu_precision)
        self.device.currentIndexChanged.connect(
            lambda _index: self.gpu_precision.setEnabled(self.device.currentData() != "cpu"))
        self.models_button = QPushButton("Manage models…")
        self.models_button.clicked.connect(lambda: self.modelsRequested.emit(str(self.model.currentData())))
        settings.addRow(self.models_button)
        self.language = QComboBox()
        for label, value in (("Auto detect", "auto"), ("Vietnamese", "vi"), ("English", "en")):
            self.language.addItem(label, value)
        settings.addRow("Language", self.language)
        self.vad = QCheckBox("Speech filtering (VAD)")
        self.vad.setChecked(True)
        self.words = QCheckBox("Word timestamps")
        self.export_selection = QCheckBox("Export selected source range only")
        settings.addRow(self.vad)
        settings.addRow(self.words)
        # Kept as a compatibility flag for existing integrations; the visible
        # scope chooser by the reviewed result is the authoritative UX.
        self.export_selection.hide()
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

        reviewed_header = QHBoxLayout()
        reviewed_header.addWidget(QLabel("Reviewed transcript"), 1)
        self.export_scope = QComboBox()
        self.export_scope.addItem("Current source", "source")
        self.export_scope.addItem("Selected source range", "range")
        self.export_scope.addItem("Whole project · clip order", "project")
        self.export_scope.setToolTip("Current source uses source time; whole project follows clip trims/order.")
        reviewed_header.addWidget(self.export_scope)
        self.export_button = QPushButton("Export transcript…")
        self.export_button.clicked.connect(self._export)
        self.export_button.setEnabled(False)
        reviewed_header.addWidget(self.export_button)
        self.open_folder_button = QPushButton("Open output folder")
        self.open_folder_button.setVisible(False)
        self.open_folder_button.clicked.connect(self._open_export_folder)
        reviewed_header.addWidget(self.open_folder_button)
        layout.addLayout(reviewed_header)
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
        for button in (
            self.speaker_button, self.split_button, self.merge_button,
            self.reset_button,
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
        self.table.itemDoubleClicked.connect(lambda _item: self.editingStarted.emit())
        self.table.cellClicked.connect(self._seek)
        layout.addWidget(self.table, 1)
        self.refresh_models()
        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._poll)

    def refresh_models(self):
        from ...model_service import ModelService
        service = ModelService()
        for index in range(self.model.count()):
            entry = get_model(str(self.model.itemData(index)))
            self.model.setItemText(index, f"{entry.label} · {service.status(entry).state}")

    def stt_options(self):
        """Resolve Auto before queueing so cached results record the actual device."""
        from ...model_service import ModelService
        from ...stt import STTOptions
        model_id = str(self.model.currentData())
        model = get_model(model_id)
        service = ModelService()
        desired = str(self.device.currentData())
        precision = str(self.gpu_precision.currentData())
        device = ("cuda" if service.is_ready(model, device="cuda", compute_type=precision)
                  else "cpu") if desired == "auto" else desired
        return STTOptions(
            model_id=model_id, language=str(self.language.currentData()),
            vad=self.vad.isChecked(), word_timestamps=self.words.isChecked(),
            device=device, compute_type=precision if device == "cuda" else "int8"
        )

    def set_media(self, source: str | None) -> None:
        if source == self._source:
            return
        if self.session is None:
            self.cancel()
        self._source = source
        self.raw_result = None
        self.document = None
        self.last_export_path = None
        self.open_folder_button.setVisible(False)
        self.export_button.setEnabled(False)
        self.table.setRowCount(0)

    def start(self) -> None:
        if self.session is not None:
            self.startRequested.emit()
            return
        if self._job_id is not None:
            return
        if not self._source or not Path(self._source).is_file():
            self.status.setText("Open a local audio/video file first.")
            return
        from dataclasses import asdict
        options = self.stt_options()
        blockers = preflight(get_model(options.model_id), device=options.device,
                             compute_type=options.compute_type)
        if blockers:
            self.status.setText("; ".join(blockers) + " · Open Settings → Models.")
            self.modelsRequested.emit(options.model_id)
            return
        self._job_id = self._manager.submit(TaskRequest(
            kind="stt", inputs={"target_path": self._source, "options": asdict(options)},
            device="gpu" if options.device == "cuda" else "cpu",
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
        self.export_button.setEnabled(True)
        self.status.setText(
            f"{len(self.document.edited)} transcript segments · {result['duration']:.1f}s"
        )
        self.resultReady.emit(result)

    def load_document(self, document: TranscriptDocument) -> None:
        """Restores reviewed project data; #8 saves the serialized document."""
        if self.session is None:
            self.cancel()
        self.document = document
        self.raw_result = {
            **document.raw_metadata,
            "segments": [s.as_dict() for s in document.raw],
        }
        self._render()
        self.export_button.setEnabled(True)

    def _render(self) -> None:
        if self.document is None:
            return
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.document.edited))
        for i, s in enumerate(self.document.edited):
            for col, text in enumerate((
                _fmt_time(s.start), _fmt_time(s.end),
                'Review speaker' if s.speaker_review_required else self.speaker_names.get(s.speaker_id, s.speaker_id) or "", s.text,
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
        self.editingStarted.emit()
        row = item.row()
        if row < len(self.document.edited):
            self.document.replace(self.document.edited[row].id, text=item.text())
            self.documentChanged.emit()

    def _selected_rows(self) -> list[int]:
        return sorted({i.row() for i in self.table.selectedIndexes()})

    def _speaker(self) -> None:
        self.editingStarted.emit()
        if self.document is None:
            return
        rows = self._selected_rows()
        if not rows:
            return
        project = self.session.project if self.session else None
        choices = {f'{speaker.name} ({speaker.id[:6]})': speaker.id for speaker in project.speakers
                   if speaker.merged_into is None} if project else {}
        if project:
            label, ok = QInputDialog.getItem(self, 'Speaker label', 'Choose a project speaker or type a new label',
                                             ['Unknown', *choices], editable=True)
        else:
            label, ok = QInputDialog.getText(self, "Speaker label", "Name (blank = unknown)")
        if ok:
            if project:
                label = label.strip()
                if label in choices:
                    label = choices[label]
                elif label and label != 'Unknown':
                    label = project.create_speaker(label).id
                else:
                    label = ''
                self.speaker_names = {speaker.id: project.speaker(speaker.id).name for speaker in project.speakers}
            for row in rows:
                self.document.replace(
                    self.document.edited[row].id,
                    speaker_id=label.strip() or None, rename_speaker=True,
                )
            self._render()
            self.documentChanged.emit()
            if self.session:
                self.session.changed.emit()

    def _split(self) -> None:
        self.editingStarted.emit()
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
        record = None
        if self.session and self.session.project:
            project = self.session.project
            item = next((item for item in project.items if item.source == self._source), None)
            if item:
                record = project.latest_analysis(item.id, 'diarization')
        self.document.apply_diarization(turns, analysis_id=record.id if record else None)
        self._render()
        self.documentChanged.emit()

    def _open_export_folder(self) -> None:
        if self.last_export_path is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.last_export_path.parent)))

    def _export(self, scope: str | None = None) -> None:
        # The same command is shared by the visible result action, File menu,
        # transcript context menu and source/project export entry points.
        if isinstance(scope, bool):  # QAction.clicked passes its checked bool.
            scope = None
        scope = scope or ("range" if self.export_selection.isChecked()
                          else str(self.export_scope.currentData()))
        project = self.session.project if self.session else None
        if scope not in ("source", "range", "project"):
            self.status.setText("Choose a valid transcript export scope")
            return
        if scope == "project":
            if project is None or not any(project.latest_analysis(m.id, "stt") for m in project.items):
                self.status.setText("Transcribe at least one project source before exporting")
                return
        elif self.document is None:
            self.status.setText("No reviewed transcript to export.")
            return
        source_range = None
        if scope == "range":
            if not self.export_range or self.export_range[1] <= self.export_range[0]:
                self.status.setText("Choose a valid source selection before exporting")
                return
            source_range = self.export_range

        stem = (project.name if scope == "project" and project else
                Path(self._source or self.document.raw_metadata.get("source", "transcript")).stem)
        suffix = "-project-transcript" if scope == "project" else "-reviewed-transcript"
        suggested = f"{stem}{suffix}.md"
        path, selected = QFileDialog.getSaveFileName(
            self, "Export reviewed transcript", suggested,
            "Markdown (*.md);;SubRip (*.srt);;Plain text (*.txt);;JSON (*.json)",
        )
        if not path:
            return
        destination = Path(path)
        formats = {"md", "txt", "srt", "json"}
        kind = destination.suffix.lstrip(".").lower()
        if not kind:
            kind = next((extension for extension in formats if f"*.{extension}" in selected), "md")
            destination = destination.with_suffix("." + kind)
        if kind not in formats:
            self.status.setText("Use .md, .txt, .srt or .json for transcript export")
            return
        try:
            self.before_export()  # Flush currently edited text before combined export.
            if scope == "project":
                content = project.combined_export(kind)
            else:
                from dataclasses import replace
                document = TranscriptDocument.restore(self.document.serialize())
                if project:
                    item = next((m for m in project.items if m.source == self._source), None)
                    if item:
                        document.raw_metadata.update(
                            current_source=item.source, media_id=item.id,
                            content_fingerprint=item.fingerprint,
                        )
                document.edited = [
                    replace(entry, speaker_id=self.speaker_names.get(entry.speaker_id, entry.speaker_id))
                    for entry in document.edited
                ]
                content = export_text(document, kind, source_range=source_range)
            # Atomic replacement avoids leaving half-written exports on an error.
            temporary = destination.with_name(destination.name + ".part")
            try:
                temporary.write_text(content, encoding="utf-8")
                os.replace(temporary, destination)
            finally:
                if temporary.exists():
                    temporary.unlink()
            self.last_export_path = destination.resolve()
            self.open_folder_button.setVisible(True)
            note = (" · Boundary words only; untimed boundary text omitted."
                    if scope in ("range", "project") else "")
            self.status.setText(f"Exported {destination.name} ({scope}){note}")
        except (OSError, ValueError, KeyError) as exc:
            self.status.setText(f"Export failed: {exc}")

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

    def commit_edit(self):
        if self.table.state() == QAbstractItemView.State.EditingState:
            editor = self.table.findChild(QLineEdit)
            if editor is not None:
                self.table.commitData(editor)
                self.table.closeEditor(editor, QAbstractItemDelegate.EndEditHint.NoHint)

    def cancel(self) -> None:
        if self.session is not None:
            self.session.cancel()
            return
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
        if self.session is None:
            self.cancel()
        if self._manager is not None:
            self._manager.close()
        super().closeEvent(event)
