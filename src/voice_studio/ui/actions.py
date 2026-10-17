"""Shared editor actions, menu placement, focus rules and portable workspace state."""
from __future__ import annotations

import json
import uuid
from dataclasses import asdict
from pathlib import Path

from PySide6.QtCore import QEvent, QSettings, Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QFileDialog, QInputDialog, QLineEdit,
    QPlainTextEdit, QTextEdit, QAbstractSpinBox, QVBoxLayout, QTextBrowser,
    QMessageBox, QMenu,
)

from ..storage import application_dir, atomic_json, read_json


class EditorActionsMixin:
    def _build_actions(self):
        self.actions = {}
        self.menus = {name: self.menuBar().addMenu(name) for name in ("File", "Edit", "Process", "View", "Settings", "Help")}

        def add(key, label, menu, callback, shortcut=None):
            action = QAction(label, self)
            if shortcut:
                action.setShortcut(QKeySequence(shortcut))
            action.triggered.connect(lambda _checked=False: self._invoke(callback))
            self.menus[menu].addAction(action)
            self.actions[key] = action
            return action

        add("new", "New project…", "File", self._new_project, "Ctrl+N")
        add("open", "Open project…", "File", self._open_project, "Ctrl+O")
        self.recent_menu = self.menus["File"].addMenu("Recent projects")
        add("import", "Import Media…", "File", self._import_media, "Ctrl+I")
        add("save", "Save", "File", self._save_project, "Ctrl+S")
        add("export", "Export reviewed transcript…", "File", self.stt_panel._export, "Ctrl+Shift+E")
        add("export_all", "Export combined project…", "File", self.projects_panel._export)
        for key, text, callback in (
            ("split", "Split transcript segment…", self.stt_panel._split),
            ("merge", "Merge transcript segments", self.stt_panel._merge),
            ("speaker", "Assign speaker…", self.stt_panel._speaker),
            ("revert", "Revert transcript", self.stt_panel._reset),
            ("relink", "Relink source…", self.projects_panel._relink),
            ("delete", "Remove selected source", self.projects_panel.remove_selected),
        ):
            add(key, text, "Edit", callback, "Delete" if key == "delete" else None)
        add("transcribe", "Transcribe selected source", "Process", self.stt_panel.start, "Ctrl+Shift+T")
        add("transcribe_all", "Transcribe all pending sources", "Process", self.projects_panel._run)
        add("match", "Match references", "Process", self._start_analysis)
        add("detect", "Auto Detect speakers…", "Process", lambda: self._show_panel(self.diarization_panel, "Auto Detect speakers"))
        add("summarize", "Summarize reviewed transcript…", "Process", lambda: self._show_panel(self.summary_panel, "Local AI draft"))
        add("cancel", "Cancel jobs", "Process", self._cancel_all, "Escape")
        add("play", "Play / Pause", "View", self._toggle_playback, "Space")
        add("zoom_in", "Zoom timeline in", "View", lambda: self.timeline.zoom(2))
        add("zoom_out", "Zoom timeline out", "View", lambda: self.timeline.zoom(.5))
        add("zoom_fit", "Fit timeline", "View", self.timeline.fit)
        add("previous", "Seek back 5 seconds", "View", lambda: self._seek_to_seconds(max(0, self.timeline._position_seconds - 5)))
        add("next", "Seek forward 5 seconds", "View", lambda: self._seek_to_seconds(self.timeline._position_seconds + 5))
        add("raw", "Raw Results…", "View", self._raw_results)
        for key, text, widget in (("sources", "Sources panel", self.projects_panel), ("inspector", "Inspector", self.inspector_tabs), ("timeline", "Timeline", self.timeline)):
            action = add(key, text, "View", lambda widget=widget: widget.setVisible(not widget.isVisible()))
            action.setCheckable(True)
            action.setChecked(True)
        add("models", "Models…", "Settings", self._open_models)
        add("inference", "Inference defaults…", "Settings", lambda: self._show_panel(self.analysis_settings_page, "Speaker matching defaults"))
        add("storage", "Model storage…", "Settings", self._open_models)
        add("docs", "Documentation", "Help", lambda: self._show_panel(self._build_help_tab(), "Documentation"))
        add("privacy", "Privacy and model terms", "Help", lambda: self._show_panel(self._build_privacy_tab(), "Privacy"))
        add("shortcuts", "Keyboard shortcuts", "Help", self._shortcuts)
        add("about", "About Voice Studio", "Help", lambda: QMessageBox.about(self, "Voice Studio", "Voice Studio 0.1 · Local-first media editor\nSpeaker similarity is not identity verification."))
        self.analyze_button.clicked.disconnect()
        self.cancel_button.clicked.disconnect()
        self.analyze_button.setDefaultAction(self.actions["match"])
        self.cancel_button.setDefaultAction(self.actions["cancel"])
        self.inspector_tabs.currentChanged.connect(self._update_actions)
        self.projects_panel.table.setContextMenuPolicy(Qt.ContextMenuPolicy.ActionsContextMenu)
        for key in ("relink", "delete", "transcribe"):
            self.projects_panel.table.addAction(self.actions[key])
        self.stt_panel.table.setContextMenuPolicy(Qt.ContextMenuPolicy.ActionsContextMenu)
        for key in ("split", "merge", "speaker", "revert", "export"):
            self.stt_panel.table.addAction(self.actions[key])
        for button in (self.stt_panel.speaker_button, self.stt_panel.split_button, self.stt_panel.merge_button, self.stt_panel.reset_button, self.stt_panel.export_button):
            button.hide()
        QApplication.instance().installEventFilter(self)
        self.projects_panel.add_button.clicked.disconnect()
        self.projects_panel.add_button.clicked.connect(lambda: self._invoke(self._import_media))
        self.projects_panel.table.cellClicked.connect(self.projects_panel._select)
        self._load_recent()

    def _invoke(self, callback):
        try:
            callback()
        except (OSError, ValueError, RuntimeError) as exc:
            QMessageBox.warning(self, "Action could not complete", str(exc))
        self._update_actions()

    def _typing(self):
        focus = QApplication.focusWidget()
        return isinstance(focus, (QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox)) or isinstance(focus, QComboBox) and focus.isEditable()

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.ShortcutOverride and self.isActiveWindow() and self._typing():
            sequence = QKeySequence(event.keyCombination())
            if any(sequence == action.shortcut() for action in self.actions.values() if not action.shortcut().isEmpty()):
                event.accept()
                return True
        return super().eventFilter(watched, event)

    def _update_actions(self):
        if not hasattr(self, "actions"):
            return
        media = self._target_path is not None
        project = self.projects_panel.project is not None
        locator_busy = self._worker is not None and self._worker.isRunning()
        stt_busy = self.stt_panel._job_id is not None
        batch_busy = bool(self.projects_panel._jobs)
        other_busy = self.diarization_panel._job_id is not None or self.summary_panel._job_id is not None
        working = locator_busy or stt_busy or batch_busy or other_busy
        self.projects_panel.table.setEnabled(not working)
        self.projects_panel.add_button.setEnabled(not working)
        document = self.stt_panel.document is not None
        rows = self.stt_panel._selected_rows()
        source_selected = self.projects_panel._selected_item() is not None
        enabled = {
            "new": not working, "open": not working, "import": not working,
            "save": project, "export": document, "export_all": project,
            "transcribe": media and not stt_busy and not batch_busy,
            "transcribe_all": project and not stt_busy and not batch_busy,
            "match": media and not locator_busy, "detect": media,
            "summarize": document, "cancel": working, "play": media and not self._typing(),
            "split": document and len(rows) == 1, "merge": document and len(rows) == 2 and rows[1] == rows[0] + 1,
            "speaker": document and bool(rows), "revert": document,
            "relink": source_selected and not working,
            "delete": source_selected and not working and self.projects_panel.table.hasFocus(),
            "raw": document or self._bundle is not None,
        }
        for key, value in enabled.items():
            self.actions[key].setEnabled(bool(value))
        active = "transcribe" if self.inspector_tabs.currentWidget() is self.stt_panel else "match"
        self.analyze_button.setDefaultAction(self.actions[active])
        for key, widget in (("sources", self.projects_panel), ("inspector", self.inspector_tabs), ("timeline", self.timeline)):
            self.actions[key].setChecked(not widget.isHidden())

    def _show_panel(self, panel, title):
        original_parent = panel.parentWidget()
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.resize(600, 650)
        layout = QVBoxLayout(dialog)
        layout.addWidget(panel)
        panel.show()
        dialog.exec()
        panel.hide()
        panel.setParent(original_parent)

    def _new_project(self):
        name, ok = QInputDialog.getText(self, "New project", "Project name", text="Untitled")
        if not ok or not name.strip():
            return
        directory = application_dir() / ".projects" / uuid.uuid4().hex
        self.projects_panel._open_folder(str(directory))
        self.projects_panel.project.name = name.strip()
        self.projects_panel.project.save()
        self._remember_project(directory)
        self.projects_panel._refresh()

    def _open_project(self):
        folder = QFileDialog.getExistingDirectory(self, "Open project", str(application_dir() / ".projects"))
        if folder:
            self.projects_panel._open_folder(folder)
            self._remember_project(Path(folder))

    def _import_media(self):
        if self.projects_panel.project is None:
            directory = application_dir() / ".projects" / uuid.uuid4().hex
            self.projects_panel._open_folder(str(directory))
            self._remember_project(directory)
        self.projects_panel._add()
        if self.projects_panel.project.items:
            row = len(self.projects_panel.project.items) - 1
            self.projects_panel.table.selectRow(row)
            self.projects_panel._select(row, 0)

    def _save_project(self):
        if self.projects_panel.project:
            self._save_project_review()
            self.projects_panel.project.save()
            self.preview_status.setText("Project and reviewed transcript saved.")

    def _store_stt_result(self, result):
        project = self.projects_panel.project
        if project is None:
            return
        item = next((item for item in project.items if Path(item.source).resolve() == Path(result["source"]).resolve()), None)
        if item is not None:
            project.begin(item.id, self.projects_panel._options())
            project.complete(item.id, result)
            self.projects_panel.active_id = item.id
            self.projects_panel._refresh()

    def _cancel_all(self):
        self._cancel_analysis()
        self.stt_panel.cancel()
        self.projects_panel.cancel()
        self.diarization_panel.cancel()
        self.summary_panel.cancel()

    def _recent_file(self):
        return application_dir() / ".settings" / "editor.json"

    def _load_recent(self):
        self.recent_menu.clear()
        for folder in read_json(self._recent_file()).get("recent", []):
            action = self.recent_menu.addAction(Path(folder).name)
            action.setToolTip(folder)
            action.triggered.connect(lambda _checked=False, folder=folder: self._invoke(lambda: self.projects_panel._open_folder(folder)))

    def _remember_project(self, folder):
        data = read_json(self._recent_file())
        data["recent"] = [str(folder)] + [item for item in data.get("recent", []) if item != str(folder)][:9]
        atomic_json(self._recent_file(), data)
        self._load_recent()

    def _restore_layout(self):
        self._layout_settings = QSettings(str(application_dir() / ".settings" / "window.ini"), QSettings.Format.IniFormat)
        for key, splitter in (("workspace", self.workspace_splitter), ("root", self.root_splitter)):
            value = self._layout_settings.value(key)
            if value is not None:
                splitter.restoreState(value)
        geometry = self._layout_settings.value("geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)

    def _save_layout(self):
        for key, splitter in (("workspace", self.workspace_splitter), ("root", self.root_splitter)):
            self._layout_settings.setValue(key, splitter.saveState())
        self._layout_settings.setValue("geometry", self.saveGeometry())
        self._layout_settings.sync()
        QApplication.instance().removeEventFilter(self)

    def _raw_results(self):
        browser = QTextBrowser()
        payload = self.stt_panel.raw_result or ({"kind": "locator", "duration": self._bundle.duration,
                   "results": [asdict(result) for result in self._bundle.results]} if self._bundle else {})
        browser.setPlainText(json.dumps(payload, ensure_ascii=False, indent=2))
        self._show_panel(browser, "Raw Results · source-local seconds")

    def _shortcuts(self):
        text = "\n".join(f"{action.shortcut().toString()}: {action.text()}" for action in self.actions.values() if not action.shortcut().isEmpty())
        QMessageBox.information(self, "Keyboard shortcuts", text + "\n\nShortcuts yield to text inputs. Delete removes a selected source only while the source table has focus.")
