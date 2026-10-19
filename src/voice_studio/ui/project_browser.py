"""Read-only project discovery and the project-first Home browser.

Discovery never instantiates ProjectStore: opening that class can migrate/save a
manifest or inspect external media. Merely opening Home must not mutate projects.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import shutil

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QHeaderView, QHBoxLayout, QInputDialog, QLabel,
    QLineEdit, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from ..projects import _atomic_write
from ..workspace import application_directory


@dataclass(frozen=True)
class ProjectSummary:
    directory: Path
    name: str
    source_count: int = 0
    duration: float | None = None
    modified: float = 0.0
    error: str = ""

    @property
    def available(self) -> bool:
        return not self.error


def scan_projects(root: Path | None = None) -> list[ProjectSummary]:
    """Read direct child manifests only; keep broken projects visible for recovery."""
    root = (Path(root) if root is not None else application_directory() / ".projects").resolve()
    if not root.is_dir():
        return []
    entries: list[ProjectSummary] = []
    for folder in root.iterdir():
        if folder.is_symlink() or not folder.is_dir():
            continue
        manifest = folder / "project.json"
        if not manifest.is_file() or manifest.is_symlink():
            continue
        try:
            if manifest.stat().st_size > 8 * 1024 * 1024:
                raise ValueError("Manifest is unusually large")
            data = json.loads(manifest.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or data.get("version") not in (1, 2):
                raise ValueError("Unsupported project manifest")
            name = data.get("name")
            if not isinstance(name, str) or not name.strip():
                name = "Untitled project"
            media = data.get("media", data.get("items", []))
            if not isinstance(media, list):
                raise ValueError("Invalid media list")
            clips = data.get("clips")
            durations = {m.get("id"): m.get("duration") for m in media if isinstance(m, dict)}
            length = 0.0
            if isinstance(clips, list):
                for clip in clips:
                    source_duration = durations.get(clip["media_id"])
                    if not isinstance(source_duration, (int, float)) or source_duration <= 0:
                        length = None
                        break
                    end = clip.get("source_out")
                    length += (float(source_duration) if end is None else float(end)) - float(clip.get("source_in", 0))
            else:
                length = sum(float(v) for v in durations.values()) if durations and all(
                    isinstance(v, (float, int)) and v > 0 for v in durations.values()
                ) else None
            entries.append(ProjectSummary(folder, name.strip(), len(media), length, manifest.stat().st_mtime))
        except (OSError, ValueError, TypeError, KeyError, AttributeError, IndexError) as exc:
            entries.append(ProjectSummary(folder, "Unreadable project", error=str(exc)))
    return sorted(entries, key=lambda p: p.modified, reverse=True)


def _clock(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    minutes, seconds = divmod(round(max(0, seconds)), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes}:{seconds:02d}"


class ProjectBrowser(QWidget):
    """A discoverable Home screen; UUID folder names are never primary UI labels."""

    openRequested = Signal(str)
    newRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.root = application_directory() / ".projects"
        self._projects: list[ProjectSummary] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        heading = QHBoxLayout()
        title = QLabel("<h2>Your projects</h2>")
        heading.addWidget(title, 1)
        new_button = QPushButton("+ New project")
        new_button.clicked.connect(self.newRequested.emit)
        heading.addWidget(new_button)
        layout.addLayout(heading)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search projects…")
        self.search.textChanged.connect(self._filter)
        layout.addWidget(self.search)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Project", "Sources", "Duration", "Modified"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in (1, 2, 3):
            self.table.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.table.cellDoubleClicked.connect(lambda _row, _col: self.open_selected())
        layout.addWidget(self.table, 1)

        actions = QHBoxLayout()
        self.details = QLabel()
        self.details.setWordWrap(True)
        actions.addWidget(self.details, 1)
        self.open_button = QPushButton("Open project")
        self.open_button.clicked.connect(self.open_selected)
        self.rename_button = QPushButton("Rename")
        self.rename_button.clicked.connect(self.rename_selected)
        self.delete_button = QPushButton("Delete…")
        self.delete_button.clicked.connect(self.delete_selected)
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refresh)
        for widget in (self.open_button, self.rename_button, self.delete_button, self.refresh_button):
            actions.addWidget(widget)
        layout.addLayout(actions)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.refresh()

    def refresh(self):
        previous = self._selected().directory if self._selected() else None
        self._projects = scan_projects(self.root)
        self._filter()
        for row in range(self.table.rowCount()):
            record = self._projects[self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)]
            if record.directory == previous:
                self.table.selectRow(row)
                break

    def _filter(self, *_):
        needle = self.search.text().strip().casefold()
        matching = [(i, p) for i, p in enumerate(self._projects)
                    if needle in p.name.casefold() or needle in p.directory.name.casefold()]
        self.table.setRowCount(len(matching))
        for row, (index, entry) in enumerate(matching):
            values = [entry.name if entry.available else "⚠ " + entry.name,
                      str(entry.source_count) if entry.available else "—",
                      _clock(entry.duration),
                      datetime.fromtimestamp(entry.modified).strftime("%Y-%m-%d %H:%M") if entry.modified else "—"]
            for col, label in enumerate(values):
                item = QTableWidgetItem(label)
                item.setData(Qt.ItemDataRole.UserRole, index)
                item.setToolTip(str(entry.directory) + ("\n" + entry.error if entry.error else ""))
                self.table.setItem(row, col, item)
        self._selection_changed()

    def _selected(self) -> ProjectSummary | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        index = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        return self._projects[index] if isinstance(index, int) and 0 <= index < len(self._projects) else None

    def _selection_changed(self):
        entry = self._selected()
        for button in (self.open_button, self.rename_button, self.delete_button):
            button.setEnabled(bool(entry and entry.available))
        self.details.setText(
            (f"{entry.name} · {entry.source_count} sources · {_clock(entry.duration)}"
             if entry and entry.available else
             f"Cannot read project: {entry.error}" if entry else
             f"{len(self._projects)} projects · Select a project or create a new one.")
        )

    def open_selected(self):
        entry = self._selected()
        if entry and entry.available:
            self.openRequested.emit(str(entry.directory))

    def rename_selected(self):
        entry = self._selected()
        if not entry or not entry.available:
            return
        name, accepted = QInputDialog.getText(self, "Rename project", "Project name", text=entry.name)
        if not accepted or not name.strip() or name.strip() == entry.name:
            return
        try:
            manifest = entry.directory / "project.json"
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            payload["name"] = name.strip()
            _atomic_write(manifest, payload)
            self.refresh()
        except (OSError, ValueError, TypeError) as exc:
            QMessageBox.warning(self, "Rename failed", str(exc))

    def delete_selected(self):
        entry = self._selected()
        if not entry or not entry.available:
            return
        if QMessageBox.question(
            self, "Delete project",
            f"Delete project '{entry.name}' and its saved analyses/reviews?\n"
            "Original linked audio/video files will NOT be deleted. This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return
        try:
            root = self.root.resolve()
            folder = entry.directory
            if folder.is_symlink() or folder.resolve().parent != root:
                raise ValueError("Refusing to delete a project outside the portable workspace")
            shutil.rmtree(folder)
            self.refresh()
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Delete failed", str(exc))
