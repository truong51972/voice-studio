from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


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


@pytest.mark.parametrize('smoke_exit', [0, 1])
def test_auto_detect_build_requires_runtime_in_the_packaged_smoke(monkeypatch, tmp_path, smoke_exit):
    build = _load_build_module()
    monkeypatch.setattr(build, 'ROOT', tmp_path)
    monkeypatch.setattr(build.sys, 'argv', ['build.py', '--with-stt', '--with-diarization'])
    monkeypatch.setattr(build, '_verify_models', lambda: None)
    monkeypatch.setattr(build, '_find_windows_onnxruntime_dll', lambda: tmp_path / 'onnxruntime.dll')
    monkeypatch.setattr(build.importlib.util, 'find_spec', lambda name: SimpleNamespace())
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        if command[0] == 'pyinstaller':
            dist = tmp_path / 'dist' / build.APP_NAME
            for relative in ('voice-studio', 'voice-studio.exe', '_internal/assets/voice-studio.png',
                             '_internal/sherpa_onnx/lib/onnxruntime.dll'):
                path = dist / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'packaged fixture')
            return SimpleNamespace(returncode=0)
        assert command[1:] == ['--smoke-test', '--require-diarization']
        return SimpleNamespace(returncode=smoke_exit, stdout='', stderr='runtime import failed' if smoke_exit else '')
    monkeypatch.setattr(build.subprocess, 'run', run)
    if smoke_exit:
        with pytest.raises(SystemExit, match='smoke test FAILED'):
            build.main()
    else:
        build.main()
    for package in ('faster_whisper', 'pyannote.audio', 'torch', 'torchaudio', 'huggingface_hub'):
        assert any(calls[0][index:index+2] == ['--collect-all', package] for index in range(len(calls[0]) - 1))
    assert len(calls) == 2


def test_default_windows_deliverables_install_and_bundle_auto_detect_runtime():
    for path in (ROOT / 'one-click.bat', ROOT / '.github/workflows/windows-release.yml'):
        text = path.read_text()
        sync = next(line for line in text.splitlines() if 'uv sync ' in line)
        build = next(line for line in text.splitlines() if 'scripts/build.py ' in line)
        assert '--extra stt' in sync and '--extra diarization' in sync
        assert '--with-stt' in build and '--with-diarization' in build


def test_packaged_smoke_does_not_swallow_a_missing_required_diarization_runtime(monkeypatch):
    import builtins
    from voice_studio import app, runtime, ui
    monkeypatch.setattr(app.sys, 'argv', ['voice-studio', '--smoke-test', '--require-diarization'])
    monkeypatch.setattr(runtime, 'configure_windows_native_runtime', lambda **kwargs: None)
    monkeypatch.setattr(ui, 'create_application', lambda args: SimpleNamespace())
    monkeypatch.setattr(ui, 'build_app', lambda: SimpleNamespace())
    original = builtins.__import__
    attempted = []
    def required_import(name, *args, **kwargs):
        if name in ('torch', 'torchaudio', 'pyannote.audio'):
            attempted.append(name)
            if name == 'pyannote.audio':
                raise ImportError('required frozen runtime missing')
            return SimpleNamespace()
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', required_import)
    with pytest.raises(ImportError, match='required frozen runtime missing'):
        app.main()
    assert attempted == ['torch', 'torchaudio', 'pyannote.audio']
