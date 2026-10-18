"""CUDA readiness is optional and never makes the CPU baseline unavailable."""
from __future__ import annotations

import os
import tomllib
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from voice_studio.model_catalog import get_model, descriptors
from voice_studio.model_service import ModelService, MANIFEST
from voice_studio.storage import atomic_json
from voice_studio.ui import create_application, build_app
from voice_studio.ui.model_manager import ModelManagerDialog


def _installed_stt(tmp_path):
    service = ModelService(tmp_path / "weights", settings=tmp_path / "settings" / "models.json")
    model = get_model("whisper-small")
    folder = service.owned_dir(model)
    folder.mkdir(parents=True)
    for asset in model.required_assets:
        (folder / asset).write_bytes(b"test")
    atomic_json(folder / MANIFEST, service._scan(model, folder, "test-revision"))
    return service, model


def test_cpu_and_cuda_profiles_are_independently_verified(tmp_path, monkeypatch):
    from voice_studio import model_service as module
    service, model = _installed_stt(tmp_path)
    command_history = []

    def ok(command, **_kwargs):
        command_history.append(command)
        return SimpleNamespace(poll=lambda: 0, returncode=0)

    monkeypatch.setattr(module.subprocess, "Popen", ok)
    service.ready(model)
    assert service.is_ready(model)
    assert not service.is_ready(model, device="cuda", compute_type="float16")
    assert service.preflight(model, device="cuda", compute_type="float16")
    service.ready(model, device="cuda", compute_type="float16")
    assert service.is_ready(model)
    assert service.is_ready(model, device="cuda", compute_type="float16")
    assert not service.is_ready(model, device="cuda", compute_type="int8_float16")
    assert not service.preflight(model, device="cuda", compute_type="float16")
    assert command_history[-1][-2:] == ["cuda", "float16"]


def test_cuda_probe_failure_does_not_remove_cpu_ready(tmp_path, monkeypatch):
    from voice_studio import model_service as module
    import pytest
    service, model = _installed_stt(tmp_path)
    monkeypatch.setattr(module.subprocess, "Popen", lambda *a, **k:
        SimpleNamespace(poll=lambda: 0, returncode=0))
    service.ready(model)
    monkeypatch.setattr(module.subprocess, "Popen", lambda *a, **k:
        SimpleNamespace(poll=lambda: 1, returncode=1, kill=lambda: None, wait=lambda: None))
    with pytest.raises(RuntimeError, match="subprocess failed"):
        service.ready(model, device="cuda", compute_type="float16")
    assert service.is_ready(model)
    assert not service.is_ready(model, device="cuda", compute_type="float16")


def test_model_manager_exposes_full_catalog_without_dropdown_iteration(tmp_path):
    app = create_application([])
    service = ModelService(tmp_path / "weights", settings=tmp_path / "settings" / "models.json")
    dialog = ModelManagerDialog(service=service, model_id="whisper-small")
    try:
        assert dialog.windowTitle() == "Models"
        assert len(dialog._items) == len(descriptors()) == 7
        assert dialog.model_list.topLevelItemCount() == 3
        assert dialog._items["whisper-small"].text(1) == "Not installed"
        assert not dialog.cuda_button.isEnabled()
        assert dialog.model_title.text() == "Small · multilingual"
        dialog.search.setText("CAM++")
        assert list(dialog._items) == ["locator-fast"]
        assert dialog.model_title.text() == "Nhanh · CAM++"
    finally:
        dialog.close()
        app.processEvents()


def test_stt_auto_resolves_cuda_only_after_verified_probe(monkeypatch):
    from voice_studio.model_service import ModelService

    app = create_application([])
    window = build_app()
    try:
        panel = window.stt_panel
        assert panel.device.currentData() == "auto"
        assert panel.stt_options().device == "cpu"
        monkeypatch.setattr(
            ModelService, "is_ready",
            lambda _self, _model, **kwargs: kwargs.get("device") == "cuda"
            and kwargs.get("compute_type") == "float16"
        )
        assert panel.stt_options().device == "cuda"
        assert panel.stt_options().compute_type == "float16"
        panel.device.setCurrentIndex(panel.device.findData("cpu"))
        assert panel.stt_options().device == "cpu"
        assert panel.stt_options().compute_type == "int8"
    finally:
        window.close()
        app.processEvents()


def test_unified_sync_targets_cuda_torch_wheels():
    project = tomllib.loads((Path(__file__).resolve().parents[1] / "pyproject.toml").read_text())
    sources = project["tool"]["uv"]["sources"]
    assert sources["torch"]["index"] == "pytorch-cu128"
    assert sources["torchaudio"]["index"] == "pytorch-cu128"
