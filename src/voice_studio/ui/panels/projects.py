"""Portable project picker/source library over the single application session."""
from dataclasses import asdict
import json
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QAbstractItemView, QFileDialog, QHBoxLayout, QInputDialog,
                               QHeaderView, QLabel, QMenu, QPushButton, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from ...projects import ProjectStore
from ...stt import STTOptions
from ...workspace import projects_directory
from ..session import ProjectSession


class ProjectsPanel(QWidget):
    openRequested = Signal(str, object)
    mediaRequested = Signal(str)
    batchRequested = Signal()

    def __init__(self, stt_panel, parent=None, *, session=None):
        super().__init__(parent)
        self.stt_panel = stt_panel
        self.session = session or ProjectSession(self)
        self.active_id = None
        self._active_document = None
        self._active_review_key = None
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
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Source", "Status", "Duration"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.cellClicked.connect(self._select)
        layout.addWidget(self.table, 1)
        self.session.changed.connect(self._refresh)
        self.session.statusChanged.connect(self.status.setText)

    @property
    def project(self):
        return self.session.project

    def _open(self):
        try:
            root = projects_directory()
            folder = QFileDialog.getExistingDirectory(self, "Open portable project", str(root))
            if folder:
                path = Path(folder).resolve()
                if path.parent != root or not (path / "project.json").is_file():
                    raise ValueError("Choose a project inside .projects alongside the app. Copy an entire legacy project folder there to restore it.")
                self._open_folder(str(path))
        except (OSError, ValueError) as exc:
            self.status.setText(str(exc))

    def _new(self):
        name, accepted = QInputDialog.getText(self, "New portable project", "Project name")
        if not accepted or not name.strip():
            return
        try:
            self.session.open(ProjectStore.create_portable(name.strip()))
            self.active_id = self._active_document = None
        except (OSError, ValueError) as exc:
            self.status.setText(str(exc))

    def _recent(self):
        try:
            manifests = sorted(projects_directory().glob("*/project.json"), key=lambda p: p.stat().st_mtime, reverse=True)
            menu = QMenu(self)
            for manifest in manifests[:10]:
                try:
                    name = json.loads(manifest.read_text(encoding="utf-8")).get("name", manifest.parent.name)
                except (OSError, ValueError, AttributeError):
                    name = manifest.parent.name
                action = menu.addAction(str(name))
                action.triggered.connect(lambda checked=False, folder=manifest.parent: self._open_folder(str(folder)))
            if manifests:
                menu.exec(self.cursor().pos())
            else:
                self.status.setText("No projects yet. Choose New to start.")
        except OSError as exc:
            self.status.setText(str(exc))

    def _open_folder(self, folder):
        try:
            project = ProjectStore(Path(folder), check_sources=False)
            self.session.open(project)
            self.active_id = self._active_document = None
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self.status.setText(f"Cannot open project: {exc}")

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
        return self.project.items[row] if self.project and 0 <= row < len(self.project.items) else None

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
        return asdict(STTOptions(model_id=str(self.stt_panel.model.currentData()),
                                language=str(self.stt_panel.language.currentData()),
                                vad=self.stt_panel.vad.isChecked(), word_timestamps=self.stt_panel.words.isChecked()))

    def _run(self):
        self.batchRequested.emit()

    def _refresh(self):
        selected = self.active_id
        self.table.setRowCount(len(self.project.items) if self.project else 0)
        if not self.project:
            return
        for row, item in enumerate(self.project.items):
            latest = next((r for r in reversed(self.project.analyses) if r.media_id == item.id), None)
            state = item.status if item.status in ('missing', 'changed') else f'{latest.task}: {latest.state}' if latest else item.status
            values = (Path(item.source).name, state, f"{item.duration:.1f}s" if item.duration else "Probe pending")
            for column, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setToolTip(item.error or (latest.error if latest else "") or item.source)
                self.table.setItem(row, column, cell)
            if item.id == selected:
                self.table.selectRow(row)
        self.status.setText(f"{self.project.name} · {len(self.project.items)} sources")

    def _select(self, row, column):
        if not self.project or not 0 <= row < len(self.project.items):
            return
        item = self.project.items[row]
        self.active_id = item.id
        self.mediaRequested.emit(item.id)
        if item.status == "completed":
            self._active_review_key = item.settings_key
            self._active_document = self.project.review(item.id)
            self.openRequested.emit(item.source, self._active_document)
        else:
            self._active_document = None

    def save_active_review(self, document):
        if self.project and self.active_id and document is self._active_document and document is not None:
            self.project.save_review(self.active_id, document, settings_key=self._active_review_key)

    def _export(self):
        if not self.project:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export ordered project", "",
                                              "Markdown (*.md);;Plain text (*.txt);;SubRip (*.srt);;JSON (*.json)")
        if path:
            try:
                kind = Path(path).suffix.lstrip('.').lower() or 'md'
                if not Path(path).suffix:
                    path += '.md'
                Path(path).write_text(self.project.combined_export(kind), encoding="utf-8")
                self.status.setText(f"Exported {Path(path).name} · Boundary text includes only fully timed words; unavailable text omitted.")
            except (ValueError, OSError) as exc:
                self.status.setText(str(exc))
