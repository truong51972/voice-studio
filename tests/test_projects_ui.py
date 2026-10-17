import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from voice_studio.ui import create_application, build_app
from voice_studio.ui.panels.projects import ProjectsPanel

def test_projects_panel_with_existing_player_and_stt_options(tmp_path):
    app = create_application([])
    window = build_app()
    try:
        assert isinstance(window.projects_panel, ProjectsPanel)
        assert window.workspace_splitter.widget(0) is window.projects_panel
        window.projects_panel._open_folder(str(tmp_path / "project"))
        assert window.projects_panel.project is not None
        assert window.projects_panel._options()["model_id"] == "whisper-small"
        from PySide6.QtMultimedia import QMediaPlayer
        assert len(window.findChildren(QMediaPlayer)) == 1
    finally:
        window.close()
        app.processEvents()
