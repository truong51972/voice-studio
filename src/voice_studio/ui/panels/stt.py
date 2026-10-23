"""STT panel: media-clock synchronized transcription, corrections, exports."""
from __future__ import annotations

from pathlib import Path
import os
from time import monotonic

from PySide6.QtCore import QEvent, Qt, QTimer, Signal, QUrl, QSignalBlocker
from PySide6.QtGui import QBrush, QColor, QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemDelegate, QAbstractItemView, QCheckBox, QComboBox, QFileDialog, QFormLayout,
    QHBoxLayout, QInputDialog, QLabel, QPushButton, QLineEdit, QMenu, QToolButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ...model_registry import descriptors, get_model, preflight
from ...task_runtime import TaskManager, TaskRequest
from ...transcript import TranscriptDocument, export_text
from ...subtitle_formats import parse_subtitles
from ...subtitle_index import SubtitleIndex
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
        self._session_progress_state = None
        self._cue_index = SubtitleIndex()
        self._cue_rows = {}
        self._user_navigation_until = 0.
        self._active_cue_row = None
        layout = QVBoxLayout(self)
        settings = QFormLayout()
        advanced = QFormLayout()
        self.transcription_settings = QWidget(self)
        self.transcription_settings.setLayout(advanced)
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
        advanced.addRow("Device", self.device)
        self.gpu_precision = QComboBox()
        self.gpu_precision.addItem("FP16 · fast", "float16")
        self.gpu_precision.addItem("INT8 + FP16 · lower VRAM", "int8_float16")
        advanced.addRow("GPU precision", self.gpu_precision)
        self.device.currentIndexChanged.connect(
            lambda _index: self.gpu_precision.setEnabled(self.device.currentData() != "cpu"))
        self.models_button = QPushButton("Manage models…")
        self.models_button.clicked.connect(lambda: self.modelsRequested.emit(str(self.model.currentData())))
        advanced.addRow(self.models_button)
        self.language = QComboBox()
        for label, value in (("Auto detect", "auto"), ("Vietnamese", "vi"), ("English", "en")):
            self.language.addItem(label, value)
        advanced.addRow("Language", self.language)
        self.vad = QCheckBox("Speech filtering (VAD)")
        self.vad.setChecked(True)
        self.words = QCheckBox("Word timestamps")
        self.export_selection = QCheckBox("Export selected source range only", self)
        advanced.addRow(self.vad)
        advanced.addRow(self.words)
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
        if self.session is not None:
            self.cancel_button.hide()  # The progress card owns the only STT cancel control.
        commands.addWidget(self.run_button)
        commands.addWidget(self.cancel_button)
        self.options_toggle = QPushButton("Options ▸")
        self.options_toggle.setCheckable(True)
        self.options_toggle.setToolTip("Language, device, GPU precision, VAD and word timestamps")
        self.options_toggle.toggled.connect(
            lambda expanded: (
                self.transcription_settings.setVisible(expanded),
                self.options_toggle.setText("Options ▾" if expanded else "Options ▸"),
            ))
        commands.addWidget(self.options_toggle)
        layout.addLayout(commands)
        layout.addWidget(self.transcription_settings)
        self.transcription_settings.hide()
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
        # Scope is chosen when exporting rather than consuming the narrow
        # right-hand inspector toolbar on every frame.
        self.export_scope.setParent(self)
        self.export_scope.hide()
        self.import_button = QPushButton("Import…")
        self.import_button.setToolTip("Load standard subtitles as a new reviewed cue track; raw STT is preserved.")
        self.import_button.clicked.connect(self._import_subtitles)
        reviewed_header.addWidget(self.import_button)
        self.export_button = QPushButton("Export transcript…")
        self.export_button.clicked.connect(self._choose_export)
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
        search_row = QHBoxLayout()
        search_row.addWidget(self.search, 1)
        self.follow_playhead = QPushButton("Follow")
        self.follow_playhead.setCheckable(True)
        self.follow_playhead.setChecked(True)
        self.follow_playhead.setToolTip("Automatically scroll to the current cue without changing your selection")
        search_row.addWidget(self.follow_playhead)
        layout.addLayout(search_row)
        self.empty_state = QLabel("Transcribe a source to generate an editable transcript.")
        self.empty_state.setWordWrap(True)
        self.empty_state.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.empty_state)
        edit_row = QHBoxLayout()
        edit_row.addWidget(QLabel("Reviewed cues"), 1)
        self.edit_menu = QToolButton()
        self.edit_menu.setText("Edit cue ▾")
        self.edit_menu.setToolTip("Select one or more transcript cues, then choose an edit action")
        self.edit_menu.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self.edit_menu)
        menu.addAction("Assign speaker…", self._speaker)
        menu.addAction("Split cue…", self._split)
        menu.addAction("Merge selected cues", self._merge)
        menu.addSeparator()
        menu.addAction("Revert reviewed cues", self._reset)
        self.edit_menu.setMenu(menu)
        edit_row.addWidget(self.edit_menu)
        layout.addLayout(edit_row)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Start", "End", "Speaker", "Text"])
        self.table.setColumnWidth(0, 86)
        self.table.setColumnWidth(1, 86)
        self.table.setColumnWidth(2, 100)
        self.table.setWordWrap(True)
        self.table.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.table.verticalHeader().setDefaultSectionSize(43)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked)
        self.table.itemChanged.connect(self._edit_text)
        self.table.itemDoubleClicked.connect(lambda _item: self.editingStarted.emit())
        self.table.cellClicked.connect(self._seek)
        self.table.viewport().installEventFilter(self)
        self.table.verticalScrollBar().sliderPressed.connect(self._mark_user_navigation)
        layout.addWidget(self.table, 1)
        self._sync_table_columns()
        self._sync_empty_state()
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

    def _sync_empty_state(self):
        empty = self.document is None
        processing = self._session_progress_state in ("queued", "running")
        self.table.setVisible(not empty)
        self.search.setVisible(not empty)
        self.follow_playhead.setVisible(not empty)
        self.edit_menu.setEnabled(not empty)
        self.empty_state.setText(
            "Transcript is being generated. You can continue reviewing the video."
            if processing else "Transcribe a source to generate an editable transcript."
        )
        self.empty_state.setVisible(empty)
        self.import_button.setEnabled(not processing)

    def set_session_progress(self, info: dict) -> None:
        self._session_progress_state = str(info.get("state", ""))
        processing = self._session_progress_state in ("queued", "running")
        self.run_button.setEnabled(not processing)
        self.status.setVisible(not processing)
        self._sync_empty_state()

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
        self._active_cue_row = None
        self._cue_index.set_entries([])
        self._cue_rows = {}
        self._sync_empty_state()

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
        self._sync_empty_state()
        self.export_button.setEnabled(True)
        issues = int(result.get("warning_count", 0))
        warning_note = f" · {issues} timestamp warning(s)" if issues else ""
        partial_note = "Partial · " if result.get("partial") else ""
        self.status.setText(
            f"{partial_note}{len(self.document.edited)} transcript segments · "
            f"{result['duration']:.1f}s{warning_note}"
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
        self._sync_empty_state()
        self.export_button.setEnabled(True)
        self.status.setText(f"{len(document.edited)} reviewed cues")

    def _render(self) -> None:
        if self.document is None:
            return
        self._active_cue_row = None
        self.table.setUpdatesEnabled(False)
        self.table.blockSignals(True)
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(self.document.edited))
        for i, s in enumerate(self.document.edited):
            for col, text in enumerate((
                _fmt_time(s.start), _fmt_time(s.end),
                'Review speaker' if s.speaker_review_required else self.speaker_names.get(s.speaker_id, s.speaker_id) or "", s.text,
            )):
                item = QTableWidgetItem(str(text))
                if col != 3:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if col in (0, 1, 2):
                    item.setToolTip(f"{_fmt_time(s.start)} – {_fmt_time(s.end)} · "
                                    f"{self.speaker_names.get(s.speaker_id, s.speaker_id) or 'Unknown'}")
                elif col == 3:
                    item.setToolTip(s.text)
                self.table.setItem(i, col, item)
        self.table.blockSignals(False)
        self.table.setUpdatesEnabled(True)
        self._cue_index.set_entries(self.document.edited)
        self._cue_rows = {entry.id: index for index, entry in enumerate(self.document.edited)}
        self._filter(self.search.text())

    def _filter(self, text: str) -> None:
        if self.document is None:
            return
        valid = set(self.document.find(text))
        for row in range(self.table.rowCount()):
            hidden = row not in valid
            if self.table.isRowHidden(row) != hidden:
                self.table.setRowHidden(row, hidden)

    def _edit_text(self, item: QTableWidgetItem) -> None:
        if self.document is None or item.column() != 3:
            return
        self.editingStarted.emit()
        row = item.row()
        if row < len(self.document.edited):
            self.document.replace(self.document.edited[row].id, text=item.text())
            self._cue_index.set_entries(self.document.edited)
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

    def _import_subtitles(self) -> None:
        if self.document is None:
            self.status.setText("Transcribe or open an existing reviewed source before importing subtitles.")
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Import subtitle cues", "",
            "Subtitle files (*.vtt *.srt);;WebVTT (*.vtt);;SubRip (*.srt)",
        )
        if not path:
            return
        kind = Path(path).suffix.lower().lstrip(".")
        if kind not in ("vtt", "srt"):
            self.status.setText("Choose a .vtt or .srt subtitle file")
            return
        try:
            cues = parse_subtitles(Path(path).read_text(encoding="utf-8-sig"), kind)
            if not cues:
                raise ValueError("Subtitle file has no valid cues")
            self.editingStarted.emit()
            self.document.load_subtitle_cues(cues)
            self._render()
            self.documentChanged.emit()
            self.status.setText(f"Imported {len(cues)} {kind.upper()} cues into reviewed transcript")
        except (OSError, UnicodeError, ValueError) as exc:
            self.status.setText(f"Subtitle import failed: {exc}")

    def _open_export_folder(self) -> None:
        if self.last_export_path is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.last_export_path.parent)))

    def _choose_export(self) -> None:
        labels = ["Current source", "Selected source range", "Whole project · clip order"]
        current = max(0, self.export_scope.currentIndex())
        selected, ok = QInputDialog.getItem(
            self, "Export transcript", "Scope", labels, current, editable=False)
        if not ok:
            return
        index = labels.index(selected)
        self.export_scope.setCurrentIndex(index)
        self._export(scope=str(self.export_scope.currentData()))

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
        suggested = f"{stem}{suffix}.vtt"
        path, selected = QFileDialog.getSaveFileName(
            self, "Export reviewed transcript", suggested,
            "WebVTT (*.vtt);;SubRip (*.srt);;Markdown (*.md);;Plain text (*.txt);;JSON (*.json)",
        )
        if not path:
            return
        destination = Path(path)
        formats = {"vtt", "srt", "md", "txt", "json"}
        kind = destination.suffix.lstrip(".").lower()
        if not kind:
            kind = next((extension for extension in ("vtt", "srt", "md", "txt", "json")
                         if f"*.{extension}" in selected), "vtt")
            destination = destination.with_suffix("." + kind)
        if kind not in formats:
            self.status.setText("Use .vtt, .srt, .md, .txt or .json for transcript export")
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

    def _sync_table_columns(self):
        # A narrow right inspector must reserve space for the actual text.
        compact = self.width() < 540
        self.table.setColumnHidden(1, compact)
        self.table.setColumnWidth(0, 78 if compact else 86)
        self.table.setColumnWidth(2, 90 if compact else 108)
        self.table.setHorizontalHeaderLabels(
            ["Start", "End", "Speaker", "Text"])

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        self._sync_table_columns()

    def _mark_user_navigation(self) -> None:
        # Playback should not steal focus/selection while a user reads or edits.
        self._user_navigation_until = monotonic() + 5.

    def eventFilter(self, watched, event):  # noqa: N802
        if watched is self.table.viewport() and event.type() in (
                QEvent.Type.Wheel, QEvent.Type.MouseButtonPress):
            self._mark_user_navigation()
        return super().eventFilter(watched, event)

    def set_playhead(self, seconds: float) -> None:
        if self.document is None or self.table.state() == QAbstractItemView.State.EditingState:
            return
        cue = self._cue_index.at(seconds)
        row = self._cue_rows.get(cue.id) if cue else None
        if row == self._active_cue_row:
            return
        # Active playback is a highlight, not table selection. Selecting a row
        # on every media tick used to destroy multi-cue user selections.
        with QSignalBlocker(self.table):
            for index, brush in ((self._active_cue_row, QBrush()),
                                 (row, QBrush(QColor("#244752")))):
                if index is not None and 0 <= index < self.table.rowCount():
                    for column in range(self.table.columnCount()):
                        cell = self.table.item(index, column)
                        if cell is not None:
                            cell.setBackground(brush)
        self._active_cue_row = row
        if (row is not None and not self.table.isRowHidden(row)
                and self.follow_playhead.isChecked()
                and monotonic() >= self._user_navigation_until):
            self.table.scrollToItem(self.table.item(row, 3),
                                    QAbstractItemView.ScrollHint.PositionAtCenter)

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
