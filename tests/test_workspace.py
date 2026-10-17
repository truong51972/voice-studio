from pathlib import Path
from types import SimpleNamespace

import pytest

from voice_studio import workspace
from voice_studio.projects import ProjectStore


def test_development_workspace_is_independent_of_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(workspace, "sys", SimpleNamespace(frozen=False))
    assert workspace.application_directory() == Path(__file__).resolve().parents[1]


def test_frozen_workspace_is_beside_executable_not_internal(tmp_path, monkeypatch):
    app = tmp_path / "VoiceStudio"
    app.mkdir()
    monkeypatch.setattr(workspace, "sys", SimpleNamespace(
        frozen=True, executable=str(app / "voice-studio.exe"), _MEIPASS=str(app / "_internal"),
    ))
    monkeypatch.chdir(tmp_path)
    assert workspace.projects_directory() == app / ".projects"
    project = ProjectStore.create_portable("Meeting")
    assert project.directory.parent == app / ".projects"
    assert ProjectStore(project.directory).id == project.id
    assert ProjectStore(project.directory).name == "Meeting"


def test_read_only_app_folder_has_no_fallback_or_partial_project(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "application_directory", lambda: tmp_path)
    def denied(*args, **kwargs):
        raise PermissionError("read-only")
    monkeypatch.setattr(workspace.tempfile, "TemporaryFile", denied)
    with pytest.raises(OSError, match="portable app folder must be writable") as error:
        ProjectStore.create_portable()
    assert "D:\\VoiceStudio" in str(error.value)
    assert list(tmp_path.iterdir()) == []


def test_read_only_project_root_is_also_reported(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "application_directory", lambda: tmp_path)
    original = workspace.tempfile.TemporaryFile
    def denied_in_projects(*args, **kwargs):
        if Path(kwargs["dir"]).name == ".projects":
            raise PermissionError("read-only project root")
        return original(*args, **kwargs)
    monkeypatch.setattr(workspace.tempfile, "TemporaryFile", denied_in_projects)
    with pytest.raises(OSError, match="portable app folder must be writable"):
        workspace.projects_directory()
    assert list((tmp_path / ".projects").iterdir()) == []


def test_actual_read_only_portable_root_is_rejected(tmp_path, monkeypatch):
    import os
    if os.name == 'nt' or os.geteuid() == 0:
        pytest.skip('POSIX write permissions require an unprivileged test user')
    root = tmp_path / 'read-only-app'
    root.mkdir()
    monkeypatch.setattr(workspace, 'application_directory', lambda: root)
    root.chmod(0o555)
    try:
        with pytest.raises(OSError, match='portable app folder must be writable'):
            ProjectStore.create_portable()
        assert not (root / '.projects').exists()
    finally:
        root.chmod(0o755)
