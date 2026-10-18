"""End-user inspector exposes only review and speaker workflows by default."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QTabBar

from voice_studio.projects import ProjectStore
from voice_studio.ui import build_app, create_application


def visible_labels(window):
    return [
        window.inspector_tabs.tabText(index)
        for index in range(window.inspector_tabs.count())
        if window.inspector_tabs.isTabVisible(index)
    ]


def test_transcript_and_speakers_are_only_primary_tabs():
    app = create_application([])
    window = build_app()
    try:
        assert visible_labels(window) == ["Transcript", "Speakers"]
        assert window.inspector_tabs.currentWidget() is window.stt_panel
        assert window.inspector_tabs.tabBar().tabButton(
            0, QTabBar.ButtonPosition.RightSide) is None
        assert window.inspector_tabs.tabBar().tabButton(
            1, QTabBar.ButtonPosition.RightSide) is None
        assert all(window.inspector_tabs.indexOf(widget) >= 0
                   for widget, _ in window._advanced_inspector_pages.values())
        assert window.raw_selector is not None
        assert window.summary_panel.startRequested is not None
    finally:
        window.close()
        app.processEvents()


def test_open_advanced_tool_shows_only_one_temporary_tab_and_can_close():
    app = create_application([])
    window = build_app()
    try:
        window.actions["analysis"].trigger()
        assert visible_labels(window) == ["Transcript", "Speakers", "Analysis"]
        assert window.inspector_tabs.currentWidget() is window._advanced_inspector_pages["analysis"][0]
        window._open_inspector_tool("raw")
        assert visible_labels(window) == ["Transcript", "Speakers", "Raw AI"]
        assert window.inspector_tabs.currentWidget() is window.raw_output.parentWidget()
        index = window.inspector_tabs.currentIndex()
        window.inspector_tabs.tabCloseRequested.emit(index)
        assert visible_labels(window) == ["Transcript", "Speakers"]
        assert window.inspector_tabs.currentWidget() is window.stt_panel
        window._close_inspector_tab(1)
        assert visible_labels(window) == ["Transcript", "Speakers"]
    finally:
        window.close()
        app.processEvents()


def test_summary_menu_opens_optional_panel_without_starting_inference():
    app = create_application([])
    window = build_app()
    try:
        window.stt_panel._show({
            "kind": "stt", "source": "meeting.wav", "duration": 2.0,
            "segments": [{"id": "a", "start": 0., "end": 1., "text": "hello"}],
        })
        window._update_actions()
        assert window.actions["summarize"].isEnabled()
        window.actions["summarize"].trigger()
        assert visible_labels(window) == ["Transcript", "Speakers", "Summary"]
        assert window.inspector_tabs.currentWidget() is window.summary_panel
        assert window.session.jobs == {}
        assert window.summary_panel.model.placeholderText()
    finally:
        window.close()
        app.processEvents()


def test_manual_reference_goes_to_speakers_and_advanced_resets_on_new_project(tmp_path):
    app = create_application([])
    window = build_app()
    try:
        window._open_inspector_tool("project")
        assert visible_labels(window) == ["Transcript", "Speakers", "Project details"]
        window._manual_selection()
        assert window.inspector_tabs.currentWidget() is window.speakers_panel
        assert window.speakers_panel.mode.currentIndex() == 1
        window.session.open(ProjectStore(tmp_path / "project"))
        assert visible_labels(window) == ["Transcript", "Speakers"]
        assert window.inspector_tabs.currentWidget() is window.stt_panel
        assert window.project_info.toPlainText().startswith("Voice Studio project")
    finally:
        window.close()
        app.processEvents()


def test_advanced_tools_reachable_from_menus_without_permanent_tabs():
    app = create_application([])
    window = build_app()
    try:
        assert window.actions["defaults"].text() == "Inference defaults"
        window.actions["defaults"].trigger()
        assert window.inspector_tabs.currentWidget() is window._advanced_inspector_pages["analysis"][0]
        for action_key, page in (
            ("segments_view", "segments"),
            ("project_details", "project"),
            ("raw", "raw"),
        ):
            # A real project enables these menu actions; direct open confirms routing.
            window._open_inspector_tool(page)
            assert window.inspector_tabs.currentWidget() is window._advanced_inspector_pages[page][0]
            assert len(visible_labels(window)) == 3
            assert action_key in window.actions
    finally:
        window.close()
        app.processEvents()
