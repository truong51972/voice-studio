from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUILD_SCRIPT = ROOT / "scripts" / "build.py"


def _load_build_module():
    spec = importlib.util.spec_from_file_location("voice_studio_build", BUILD_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_windows_build_uses_valid_png_icon_source() -> None:
    build = _load_build_module()
    assert build.APP_ICON.name == "voice-studio.png"
    assert build.APP_ICON.read_bytes().startswith(build.PNG_SIGNATURE)
    build._verify_assets()


def test_build_refuses_to_replace_portable_user_projects(tmp_path):
    import pytest
    build = _load_build_module()
    projects = tmp_path / ".projects"
    projects.mkdir()
    manifest = projects / "project.json"
    manifest.write_text("important")
    with pytest.raises(SystemExit, match="Refusing to overwrite"):
        build._protect_portable_projects(tmp_path)
    assert manifest.read_text() == "important"


def test_optional_diarization_build_fails_before_packaging_when_runtime_is_missing(monkeypatch, tmp_path):
    import pytest
    build = _load_build_module()
    monkeypatch.setattr(build, 'ROOT', tmp_path)
    monkeypatch.setattr(build.sys, 'argv', ['build.py', '--with-diarization'])
    monkeypatch.setattr(build, '_verify_models', lambda: None)
    monkeypatch.setattr(build.importlib.util, 'find_spec', lambda name: None)
    def unexpected(*args, **kwargs):
        raise AssertionError('Do not invoke PyInstaller with missing dependencies')
    monkeypatch.setattr(build.subprocess, 'run', unexpected)
    with pytest.raises(SystemExit, match='uv sync --dev --extra diarization'):
        build.main()
