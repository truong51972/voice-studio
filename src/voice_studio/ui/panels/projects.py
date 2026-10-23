"""Portable project picker/source library over the single application session."""
from dataclasses import asdict
import json
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QAbstractItemView, QFileDialog, QHBoxLayout, QInputDialog,
                               QHeaderView, QLabel, QMenu, QPushButton, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from ...projects import ProjectStore
from ...workspace import projects_directory
from ..session import ProjectSession


class ClipOrderTable(QTableWidget):
    """Keep Qt's drag gesture, but commit a domain-level clip-ID reorder."""

    reorderRequested = Signal(object)

    @staticmethod
    def reordered_ids(ids: list[str], source: int, target: int) -> list[str]:
        """Calculate the new clip order without mutating Qt's table model."""
        if not 0 <= source < len(ids):
            raise ValueError("Invalid drag source")
        target = max(0, min(len(ids), target))
        result = list(ids)
        moved = result.pop(source)
        if target > source:
            target -= 1
        result.insert(target, moved)
        return result

    def dropEvent(self, event):
        selected = self.selectionModel().selectedRows()
        source = selected[0].row() if len(selected) == 1 else -1
        if source < 0 or self.rowCount() < 2 or event.source() is not self:
            event.ignore()
            return
        indicator = self.dropIndicatorPosition()
        if indicator == QAbstractItemView.DropIndicatorPosition.OnItem:
            event.ignore()  # Reordering is between rows, not onto a source.
            return
        target = self.rowAt(round(event.position().y()))
        if target < 0:
            target = self.rowCount()
        elif indicator == QAbstractItemView.DropIndicatorPosition.BelowItem:
            target += 1
        current = [self.item(row, 0).data(Qt.ItemDataRole.UserRole)
                   for row in range(self.rowCount())]
        ordered = self.reordered_ids(current, source, target)
        event.acceptProposedAction()
        if ordered != current:
            # Never rebuild/reset a QTableWidget from inside its active dropEvent:
            # the view is still processing the drag and holds row/model indices.
            QTimer.singleShot(0, lambda ids=ordered: self.reorderRequested.emit(ids))


class ProjectsPanel(QWidget):
    openRequested = Signal(str, object)
    mediaRequested = Signal(str)
    batchRequested = Signal()
    clipRequested = Signal(str)
    clipOrderRequested = Signal(object)

    def __init__(self, stt_panel, parent=None, *, session=None):
        super().__init__(parent)
        self.stt_panel = stt_panel
        self.session = session or ProjectSession(self)
        self.active_id = None
        self.active_clip_id = None
        self._active_document = None
        self._active_review_key = None
        self._saved_review_version = None
        layout = QVBoxLayout(self)
        buttons = QHBoxLayout()
        buttons.addWidget(QLabel("Sources"), 1)
        self.add_button = QPushButton("+")
        self.add_button.setToolTip("Import media (Ctrl+I)")
        self.add_button.clicked.connect(self._add)
        buttons.addWidget(self.add_button)
        layout.addLayout(buttons)
        self.status = QLabel("New/Open project · external media references")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.table = ClipOrderTable(0, 3)
        self.table.setHorizontalHeaderLabels(["Source", "Status", "Duration"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setDragEnabled(True)
        self.table.setAcceptDrops(True)
        self.table.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.table.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.table.setDropIndicatorShown(True)
        self.table.setToolTip("Drag a row to reorder playback and combined exports")
        self.table.reorderRequested.connect(self.clipOrderRequested.emit)
        self.table.cellClicked.connect(self._select)
        self.table.itemActivated.connect(lambda item: self._select(item.row(), item.column()))
        layout.addWidget(self.table, 1)
        self.session.changed.connect(self._refresh)
        self.session.statusChanged.connect(self.status.setText)

    @property
    def project(self):
        return self.session.project

    def _open(self):
        # Open the auto-discovered project browser rather than asking users
        # to identify a UUID directory in the native folder picker.
        self.window()._show_home()

    def _new(self):
        name, accepted = QInputDialog.getText(self, "New portable project", "Project name")
        if not accepted or not name.strip():
            return
        try:
            self.session.open(ProjectStore.create_portable(name.strip()))
            self.active_id = self._active_document = None
        except (OSError, ValueError) as exc:
            self.status.setText(str(exc))
            if hasattr(self.window(), "picker_status"):
                self.window().picker_status.setText(str(exc))

    def _recent(self):
        self._open()

    def _open_folder(self, folder):
        try:
            if self.session.jobs:
                raise ValueError("Finish or cancel project jobs before switching projects")
            project = ProjectStore(Path(folder), check_sources=False)
            self.session.open(project)
            self.active_id = self._active_document = None
        except (OSError, ValueError, KeyError, TypeError) as exc:
            message = f"Cannot open project: {exc}"
            self.status.setText(message)
            if hasattr(self.window(), "picker_status"):
                self.window().picker_status.setText(message)

    def _add(self):
        if self.project is None:
            self.status.setText("Create/open a project first")
            return
        paths, _ = QFileDialog.getOpenFileNames(self, "Import media", "",
            "Media (*.m4a *.mp3 *.wav *.flac *.ogg *.aac *.mp4 *.mkv *.mov *.avi *.webm *.m4v);;All files (*)")
        if paths:
            try:
                self.session.import_media(paths)
            except (ValueError, OSError) as exc:
                self.status.setText(str(exc))

    def _selected_item(self):
        row = self.table.currentRow()
        if not self.project or not 0 <= row < len(self.project.clips):
            return None
        return self.project.get(self.project.clips[row].media_id)

    def _relink(self):
        item = self._selected_item()
        if item:
            path, _ = QFileDialog.getOpenFileName(self, "Relink source media")
            if path:
                try:
                    self.session.relink(item.id, path)
                except (ValueError, OSError) as exc:
                    self.status.setText(str(exc))

    def _options(self):
        return asdict(self.stt_panel.stt_options())

    def _run(self):
        self.batchRequested.emit()

    def _refresh(self):
        selected = self.active_clip_id
        self.table.setRowCount(len(self.project.clips) if self.project else 0)
        if not self.project:
            return
        for row, clip in enumerate(self.project.clips):
            item = self.project.get(clip.media_id)
            records = [r for r in self.project.analyses if r.media_id == item.id]
            latest_by_task = {record.task: record for record in records}
            latest = records[-1] if records else None
            if item.status in ("missing", "changed"):
                state = item.status.capitalize()
            else:
                labels = []
                for task, label in (("stt", "STT"), ("diarization", "Speakers"),
                                    ("locator", "Match")):
                    record = latest_by_task.get(task)
                    if ((record and record.state == "completed") or
                            (task == "stt" and not record and item.status == "completed")):
                        # Older portable projects stored STT completion directly
                        # on the media item, not as an AnalysisRecord.
                        labels.append(label + " ✓")
                if latest and latest.state in ("running", "pending", "queued", "failed"):
                    labels.append(f"{latest.task}: {latest.state}")
                state = " · ".join(labels) or (item.status.capitalize() if item.status else "Ready")
            duration = None
            if item.duration is not None and item.duration > 0:
                seconds = round(item.duration)
                h, remainder = divmod(seconds, 3600)
                m, sec = divmod(remainder, 60)
                duration = f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"
            values = (f"{row + 1}. {Path(item.source).name}", state, duration or "Probing…")
            detail = " · ".join(f"{record.task}: {record.state}" for record in records)
            if item.status == "completed" and "stt" not in latest_by_task:
                detail = "stt: completed" + (" · " + detail if detail else "")
            hint = "\n".join(filter(None, [str(item.source), detail, item.error,
                                            latest.error if latest else None]))
            for column, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setData(Qt.ItemDataRole.UserRole, clip.id)
                cell.setToolTip(hint)
                self.table.setItem(row, column, cell)
            if clip.id == selected:
                self.table.selectRow(row)
        self.status.setText(f"{self.project.name} · {len(self.project.clips)} clips")

    def _select(self, row, column):
        if not self.project or not 0 <= row < len(self.project.clips):
            return
        clip = self.project.clips[row]
        item = self.project.get(clip.media_id)
        self.active_id = item.id
        self.active_clip_id = clip.id
        self.clipRequested.emit(clip.id)
        if item.status == "completed":
            self._active_review_key = item.settings_key
            self._active_document = self.project.review(item.id)
            self._saved_review_version = (id(self._active_document), self._active_document.revision)
            self.openRequested.emit(item.source, self._active_document)
        else:
            self._active_document = None

    def save_active_review(self, document):
        if not (self.project and self.active_id and
                document is self._active_document and document is not None):
            return
        version = (id(document), document.revision)
        if version == self._saved_review_version:
            return
        self.project.save_review(self.active_id, document, settings_key=self._active_review_key)
        self._saved_review_version = version

    def _export(self):
        # Both File → Export project transcript and the STT result action use
        # one scope-aware export implementation. No independent save path.
        self.stt_panel._export(scope="project")
