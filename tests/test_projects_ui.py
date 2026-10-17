import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from voice_studio.ui import create_application, build_app
from voice_studio.ui.panels.projects import ProjectsPanel

def test_projects_panel_with_existing_player_and_stt_options(tmp_path):
    app = create_application([])
    window = build_app()
    try:
        assert isinstance(window.projects_panel, ProjectsPanel)
        assert window.inspector_tabs.tabText(4) == "Projects"
        window.projects_panel._open_folder(str(tmp_path / "project"))
        assert window.projects_panel.project is not None
        assert window.projects_panel._options()["model_id"] == "whisper-small"
        from PySide6.QtMultimedia import QMediaPlayer
        assert len(window.findChildren(QMediaPlayer)) == 1
    finally:
        window.close()
        app.processEvents()


def test_new_project_is_portable_and_storage_failure_is_visible(tmp_path, monkeypatch):
    from voice_studio import workspace
    from voice_studio.ui.panels import projects
    monkeypatch.setattr(workspace, "application_directory", lambda: tmp_path)
    monkeypatch.setattr(projects.QInputDialog, "getText", lambda *args: ("Meeting", True))
    app = create_application([])
    window = build_app()
    try:
        panel = window.projects_panel
        panel._new()
        project = panel.project
        assert project.name == "Meeting"
        assert project.directory.parent == tmp_path / ".projects"
        def deny(*args, **kwargs):
            raise PermissionError("read-only")
        monkeypatch.setattr(workspace.tempfile, "TemporaryFile", deny)
        panel._new()
        assert "portable app folder must be writable" in panel.status.text()
        assert panel.project is project
    finally:
        window.close()
        app.processEvents()


def test_relinked_review_saves_to_active_media_only(tmp_path):
    from voice_studio.projects import ProjectStore
    from voice_studio.transcript import TranscriptDocument
    source = tmp_path / "original.wav"
    source.write_bytes(b"audio")
    project = ProjectStore(tmp_path / "project")
    project.add([source])
    item = project.items[0]
    result = {"kind": "stt", "source": str(source), "duration": 2.,
              "segments": [{"id": "s1", "start": 0., "end": 1., "text": "Original"}]}
    project.begin(item.id, {})
    project.complete(item.id, result)
    moved = tmp_path / "moved.wav"
    source.rename(moved)
    project.relink(item.id, moved)
    app = create_application([])
    window = build_app()
    try:
        panel = window.projects_panel
        panel._open_folder(str(project.directory))
        panel._select(0, 0)
        document = window.stt_panel.document
        document.replace("s1", text="Corrected")
        panel.save_active_review(document)
        unrelated = TranscriptDocument(result)
        unrelated.replace("s1", text="Stale unrelated job")
        panel.save_active_review(unrelated)
        assert panel.project.review(item.id).edited[0].text == "Corrected"
    finally:
        window.close()
        app.processEvents()
