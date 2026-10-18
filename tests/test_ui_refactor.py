import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QDialog, QMainWindow, QPushButton

from voice_studio.ui import build_app, create_application


def test_project_first_menu_structure_and_shortcuts():
    app = create_application([])
    window = build_app()
    try:
        assert isinstance(window, QMainWindow)
        assert [menu.title() for menu in window.menus.values()] == [
            "File", "Edit", "Process", "View", "Settings", "Help"
        ]
        assert window.actions["new"].shortcut() == QKeySequence("Ctrl+N")
        assert window.actions["save"].shortcut() == QKeySequence("Ctrl+S")
        assert window.actions["transcribe"].shortcut() == QKeySequence("Ctrl+Shift+T")
        assert window.actions["play"].shortcut() == QKeySequence("Space")
        assert window.actions["models"].text() == "Models"
        assert window.pages.currentIndex() == 0
    finally:
        window.close()
        app.processEvents()


def test_dialog_titles_omit_parent_menu_breadcrumbs(monkeypatch):
    app = create_application([])
    window = build_app()
    captured = []
    def capture_dialog(dialog):
        captured.append(dialog.windowTitle())
        return 0
    monkeypatch.setattr(QDialog, "exec", capture_dialog)
    try:
        window._show_documentation()
        assert captured == ["Documentation"]
        # The adjacent Manage models button already provides the navigation.
        assert window.diarization_panel.model_folder.placeholderText() == "Community-1 model directory"
    finally:
        window.close()
        app.processEvents()


def test_source_sidebar_is_compact_and_stt_actions_move_to_context_menu():
    app = create_application([])
    window = build_app()
    try:
        source_buttons = [button for button in window.projects_panel.findChildren(QPushButton)
                          if button.parentWidget() is window.projects_panel]
        assert [button.text() for button in source_buttons] == ["+"]
        assert window.models_button.isHidden()
        assert window.stt_panel.split_button.isHidden()
        assert window.stt_panel.table.actions()
        assert "Not installed" in window.stt_panel.model.itemText(0)
    finally:
        window.close()
        app.processEvents()
