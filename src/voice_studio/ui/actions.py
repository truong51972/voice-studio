"""Menu-first commands for the project-first editor (no duplicate UI state)."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, QTimer, Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QAbstractItemView, QAbstractSpinBox, QComboBox, QDialog,
    QLineEdit, QPlainTextEdit, QTextEdit, QMessageBox, QVBoxLayout,
)

from ..workspace import projects_directory


class EditorActionsMixin:
    def _build_actions(self):
        self.actions = {}
        self.menus = {name: self.menuBar().addMenu(name) for name in
                      ("File", "Edit", "Process", "View", "Settings", "Help")}

        def add(key, title, menu, callback, shortcut=None):
            action = QAction(title, self)
            if shortcut:
                action.setShortcut(QKeySequence(shortcut))
            action.triggered.connect(lambda _checked=False, fn=callback: self._invoke_action(fn))
            (self.menus[menu] if isinstance(menu, str) else menu).addAction(action)
            self.actions[key] = action
            return action

        add("new", "New project", "File", self.projects_panel._new, "Ctrl+N")
        add("open", "Open project", "File", self.projects_panel._open, "Ctrl+O")
        self.recent_menu = self.menus["File"].addMenu("Recent projects")
        self.recent_menu.aboutToShow.connect(self._refresh_recent_menu)
        add("import", "Import media", "File", self.projects_panel._add, "Ctrl+I")
        add("import_subtitles", "Import subtitles (.vtt/.srt)", "File", self.stt_panel._import_subtitles)
        add("save", "Save project", "File", self._save, "Ctrl+S")
        add("export", "Export project transcript", "File", self.projects_panel._export, "Ctrl+Shift+E")
        add("export_stt", "Export transcript", "File", self.stt_panel._choose_export)

        add("move_back", "Move clip earlier", "Edit", lambda: self._move_clip(-1))
        add("move_forward", "Move clip later", "Edit", lambda: self._move_clip(1))
        add("trim", "Apply source trim", "Edit", self._trim_clip)
        add("speaker", "Assign transcript speaker", "Edit", self.stt_panel._speaker)
        add("split", "Split transcript segment", "Edit", self.stt_panel._split)
        add("merge", "Merge transcript segments", "Edit", self.stt_panel._merge)
        add("revert", "Revert transcript edits", "Edit", self.stt_panel._reset)
        add("relink", "Relink source", "Edit", self.projects_panel._relink)

        add("transcribe", "Transcribe selected source", "Process", lambda: self._run_stt(False), "Ctrl+Shift+T")
        add("transcribe_all", "Transcribe whole project", "Process", lambda: self._run_stt(True))
        add("detect", "Auto Detect Speakers", "Process", self._process_auto_detect)
        add("match", "Match manual references", "Process", self._process_match)
        add("compare", "Compare project speakers", "Process", self._compare)
        # Optional AI summarization remains available, but is not a permanent
        # navigation destination. The panel owns model settings and the Run button.
        add("summarize", "Summarize…", "Process", lambda: self._open_inspector_tool("summary"))
        add("cancel", "Cancel jobs", "Process", self.session.cancel, "Escape")

        add("play", "Play / Pause", "View", self.playback.toggle, "Space")
        add("preview", "Preview selected range", "View", self._preview_selection)
        add("zoom_fit", "Fit timeline", "View", lambda: (self.zoom.setValue(1), self.pan.setValue(0)))
        self.advanced_menu = self.menus["View"].addMenu("Advanced tools")
        add("analysis", "Analysis / similarity", self.advanced_menu,
            lambda: self._open_inspector_tool("analysis"))
        add("segments_view", "Detection segments", self.advanced_menu,
            lambda: self._open_inspector_tool("segments"))
        add("project_details", "Project details", self.advanced_menu,
            lambda: self._open_inspector_tool("project"))
        add("raw", "Raw AI results", self.advanced_menu,
            lambda: self._open_inspector_tool("raw"))
        subtitles = add("subtitles", "Show subtitles", "View", self._toggle_subtitles)
        subtitles.setCheckable(True)
        subtitles.setChecked(True)
        for key, name, widget in (
            ("sources", "Sources panel", self.projects_panel),
            ("inspector", "Inspector", self.inspector_tabs),
            ("timeline", "Timeline", self.root_splitter.widget(1)),
        ):
            action = add(key, name, "View", lambda target=widget: target.setVisible(not target.isVisible()))
            action.setCheckable(True)
            action.setChecked(True)

        add("models", "Models", "Settings", self._open_models)
        add("defaults", "Inference defaults", "Settings",
            lambda: self._open_inspector_tool("analysis"))
        add("storage", "Model storage", "Settings", self._open_models)

        add("docs", "Documentation", "Help", self._show_documentation)
        add("shortcuts", "Keyboard shortcuts", "Help", self._show_shortcuts)
        add("about", "About Voice Studio", "Help", lambda: QMessageBox.about(
            self, "Voice Studio", "Local-first audio/video analysis and transcript review."))

        self.projects_panel.table.setContextMenuPolicy(Qt.ContextMenuPolicy.ActionsContextMenu)
        for key in ("relink", "transcribe", "transcribe_all", "export"):
            self.projects_panel.table.addAction(self.actions[key])
        self.stt_panel.table.setContextMenuPolicy(Qt.ContextMenuPolicy.ActionsContextMenu)
        for key in ("speaker", "split", "merge", "revert", "export_stt"):
            self.stt_panel.table.addAction(self.actions[key])
        for button in (self.stt_panel.speaker_button, self.stt_panel.split_button,
                       self.stt_panel.merge_button, self.stt_panel.reset_button):
            button.hide()
        app = QApplication.instance()
        app.installEventFilter(self)
        self._action_timer = QTimer(self)
        self._action_timer.setInterval(250)
        self._action_timer.timeout.connect(self._update_actions)
        self._action_timer.start()
        self._update_actions()

    def _invoke_action(self, callback):
        self._guard(callback)
        self._update_actions()

    def _process_auto_detect(self):
        self.speakers_panel.mode.setCurrentIndex(0)
        self._run_diarization()

    def _process_match(self):
        self.speakers_panel.mode.setCurrentIndex(1)
        self._start_analysis()

    def _refresh_recent_menu(self):
        self.recent_menu.clear()
        try:
            folders = sorted(projects_directory().glob("*/project.json"),
                             key=lambda path: path.stat().st_mtime, reverse=True)
        except OSError:
            folders = []
        for manifest in folders[:10]:
            action = self.recent_menu.addAction(manifest.parent.name)
            action.triggered.connect(lambda _checked=False, folder=manifest.parent:
                                     self._invoke_action(lambda: self.projects_panel._open_folder(str(folder))))
        if not folders:
            self.recent_menu.addAction("No recent projects").setEnabled(False)

    def _show_documentation(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Documentation")
        dialog.resize(730, 620)
        layout = QVBoxLayout(dialog)
        layout.addWidget(self._help())
        dialog.exec()

    def _show_shortcuts(self):
        pairs = [f"{action.shortcut().toString()}: {action.text()}"
                 for action in self.actions.values() if not action.shortcut().isEmpty()]
        QMessageBox.information(self, "Keyboard shortcuts", "\n".join(pairs)
                                + "\n\nPlayback and Delete shortcuts do not override text editing.")

    def _typing(self):
        focus = QApplication.focusWidget()
        if isinstance(focus, (QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox)):
            return True
        if isinstance(focus, QComboBox) and focus.isEditable():
            return True
        table = focus
        while table is not None:
            if isinstance(table, QAbstractItemView) and table.state() == QAbstractItemView.State.EditingState:
                return True
            table = table.parentWidget()
        return False

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.ShortcutOverride and self.isActiveWindow() and self._typing():
            sequence = QKeySequence(event.keyCombination())
            if any(sequence == action.shortcut() for action in self.actions.values()
                   if not action.shortcut().isEmpty()):
                event.accept()
                return True
        return super().eventFilter(watched, event)

    def _update_actions(self):
        if not hasattr(self, "actions"):
            return
        project = self.session.project is not None
        selection = self._current_clip() is not None if project else False
        working = bool(self.session.jobs)
        transcript = self.stt_panel.document is not None
        rows = self.stt_panel._selected_rows() if transcript else []
        enabled = {
            "new": not working, "open": not working,
            "import": project and not working, "save": project,
            "export": project and any(self.session.project.latest_analysis(m.id, "stt")
                for m in self.session.project.items), "export_stt": transcript,
            "import_subtitles": transcript,
            "move_back": selection and not working, "move_forward": selection and not working,
            "trim": selection and not working,
            "split": transcript and len(rows) == 1, "merge": transcript and len(rows) == 2 and rows[1] == rows[0] + 1,
            "speaker": transcript and bool(rows), "revert": transcript,
            "relink": selection and not working,
            "transcribe": selection and not working, "transcribe_all": project and not working,
            "detect": selection and not working, "match": selection and not working,
            "compare": project and not working, "summarize": transcript and not working,
            "cancel": working, "play": selection and not self._typing(),
            "preview": selection, "raw": project,
            "segments_view": project, "project_details": project,
            "analysis": True,
        }
        self.stt_panel.export_button.setEnabled(bool(transcript or enabled["export"]))
        self.cancel_button.setVisible(working)
        for key, value in enabled.items():
            self.actions[key].setEnabled(bool(value))
        for key, widget in (("sources", self.projects_panel),
                            ("inspector", self.inspector_tabs),
                            ("timeline", self.root_splitter.widget(1))):
            self.actions[key].setChecked(not widget.isHidden())

    def _stop_actions(self):
        self._action_timer.stop()
        QApplication.instance().removeEventFilter(self)
