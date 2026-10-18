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


def test_build_uses_valid_png_icon_source():
    build = _load_build_module()
    assert build.APP_ICON.name == "voice-studio.png"
    assert build.APP_ICON.read_bytes().startswith(build.PNG_SIGNATURE)
    build._verify_assets()


@pytest.mark.parametrize("name", [".projects", ".models", ".settings"])
def test_build_preserves_existing_portable_user_data(tmp_path, name):
    build = _load_build_module()
    directory = tmp_path / name
    directory.mkdir()
    important = directory / "important.txt"
    important.write_text("do not delete")
    with pytest.raises(SystemExit, match="Refusing to overwrite"):
        build._protect_portable_data(tmp_path)
    assert important.read_text() == "do not delete"


def test_missing_required_runtime_blocks_packaging(monkeypatch, tmp_path):
    from voice_studio import diagnostics
    build = _load_build_module()
    monkeypatch.setattr(build, "ROOT", tmp_path)
    entrypoint = tmp_path / "app.py"
    entrypoint.write_text("pass")
    monkeypatch.setattr(build, "APP_ENTRYPOINT", entrypoint)
    monkeypatch.setattr(build, "_verify_assets", lambda: None)
    monkeypatch.setattr(build.sys, "argv", ["build.py"])
    monkeypatch.setattr(diagnostics, "runtime_import_errors",
                        lambda: {"pyannote.audio": "missing shared library"})
    monkeypatch.setattr(build.subprocess, "run",
                        lambda *_args, **_kwargs: pytest.fail("Should not invoke PyInstaller"))
    with pytest.raises(SystemExit, match="Repair required production runtimes"):
        build.main()


@pytest.mark.parametrize("smoke_exit", [0, 1])
def test_packaged_build_requires_full_native_runtime_smoke(monkeypatch, tmp_path, smoke_exit):
    from voice_studio import diagnostics
    build = _load_build_module()
    monkeypatch.setattr(build, "ROOT", tmp_path)
    entrypoint = tmp_path / "app.py"
    entrypoint.write_text("pass")
    monkeypatch.setattr(build, "APP_ENTRYPOINT", entrypoint)
    monkeypatch.setattr(build, "_verify_assets", lambda: None)
    monkeypatch.setattr(build.sys, "argv", ["build.py"])
    monkeypatch.setattr(diagnostics, "runtime_import_errors", lambda: {})
    monkeypatch.setattr(build, "_find_windows_onnxruntime_dll", lambda: tmp_path / "onnxruntime.dll")
    calls = []

    def run(command, **_kwargs):
        calls.append(command)
        if command[0] == "pyinstaller":
            dist = tmp_path / "dist" / build.APP_NAME
            required = [
                "voice-studio.exe" if build.os.name == "nt" else "voice-studio",
                "_internal/assets/voice-studio.png",
                "_internal/voice_studio/configs/models/stt.json",
                "_internal/voice_studio/configs/models/speaker_matching.json",
                "_internal/voice_studio/configs/models/diarization.json",
            ]
            if build.os.name == "nt":
                required.append("_internal/sherpa_onnx/lib/onnxruntime.dll")
            for name in required:
                destination = dist / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(b"fixture")
            return SimpleNamespace(returncode=0)
        assert command[1:] == ["--smoke-test"]
        return SimpleNamespace(returncode=smoke_exit, stdout="", stderr="native failure" if smoke_exit else "")

    monkeypatch.setattr(build.subprocess, "run", run)
    if smoke_exit:
        with pytest.raises(SystemExit, match="smoke test FAILED"):
            build.main()
    else:
        build.main()
    assert len(calls) == 2
    assert any(calls[0][i:i + 2] == ["--collect-all", "pyannote.audio"]
               for i in range(len(calls[0]) - 1))
    assert any(calls[0][i:i + 2] == ["--collect-all", "torch"]
               for i in range(len(calls[0]) - 1))


def test_default_windows_release_installs_all_runtimes_without_extras():
    for path in (ROOT / "one-click.bat", ROOT / ".github/workflows/windows-release.yml"):
        commands = path.read_text()
        assert "uv sync --locked" in commands
        assert "--extra stt" not in commands
        assert "--extra diarization" not in commands
        assert "scripts/build.py" in commands


def test_packaged_smoke_propagates_missing_native_dependency(monkeypatch):
    from voice_studio import app, diagnostics, runtime, ui
    monkeypatch.setattr(app.sys, "argv", ["voice-studio", "--smoke-test"])
    monkeypatch.setattr(runtime, "configure_windows_native_runtime", lambda **kwargs: None)
    monkeypatch.setattr(ui, "create_application", lambda argv: SimpleNamespace())
    monkeypatch.setattr(ui, "build_app", lambda: SimpleNamespace())
    monkeypatch.setattr(diagnostics, "runtime_import_errors",
                        lambda: {"pyannote.audio": "Native library missing"})
    with pytest.raises(RuntimeError, match="Native library missing"):
        app.main()


def test_only_python_312_is_supported_and_ci_matches():
    """Release, package metadata and test runners must agree on Python support."""
    import tomllib

    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    lock = (ROOT / "uv.lock").read_text(encoding="utf-8")
    workflow = (ROOT / ".github/workflows/tests.yml").read_text(encoding="utf-8")
    release = (ROOT / ".github/workflows/windows-release.yml").read_text(encoding="utf-8")
    one_click = (ROOT / "one-click.bat").read_text(encoding="utf-8")
    assert project["project"]["requires-python"] == ">=3.12,<3.13"
    assert 'requires-python = ">=3.12, <3.13"' in lock
    assert (ROOT / ".python-version").read_text(encoding="utf-8").strip() == "3.12"
    assert 'python: ["3.12"]' in workflow
    assert 'python: ["3.11"' not in workflow
    assert "uv sync --locked --python 3.12" in one_click
    assert "uv sync --locked --python 3.12" in release
