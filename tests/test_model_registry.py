import hashlib
import json

import pytest

from voice_studio import model_registry as catalog
from voice_studio.model_registry import (
    descriptors, get_model, installed, model_path, preflight, uninstall,
)

def test_catalog_is_task_aware_and_preserves_locator_checksums():
    models = descriptors()
    assert len(descriptors("locator")) == 2
    assert len(descriptors("stt")) == 4
    assert get_model("locator-fast").sha256 is not None
    assert get_model("whisper-small").engine == "faster-whisper"
    assert all(m.id for m in models)
    with pytest.raises(KeyError):
        get_model("unknown")

def test_local_installed_snapshot_requires_complete_manifest(tmp_path):
    model = get_model("whisper-small")
    directory = model_path(model, tmp_path)
    directory.mkdir()
    (directory / "model.bin").write_bytes(b"weights")
    (directory / "config.json").write_text("{}")
    (directory / "tokenizer.json").write_text("{}")
    hashes = {}
    for name in model.required_assets:
        hashes[name] = hashlib.sha256((directory / name).read_bytes()).hexdigest()
    (directory / "voice-studio-manifest.json").write_text(json.dumps({
        "id": model.id, "resolved_revision": "a" * 40, "sha256": hashes
    }))
    assert installed(model, tmp_path)
    (directory / "model.bin").write_bytes(b"corrupt")
    assert not installed(model, tmp_path)
    uninstall(model, tmp_path)
    assert not directory.exists()

def test_missing_stt_dependencies_and_models_are_explained(tmp_path):
    model = get_model("whisper-small")
    errors = preflight(model, root=tmp_path)
    assert any("not installed" in error for error in errors)
    assert any("CUDA" in error for error in preflight(model, device="cuda", root=tmp_path))
    assert any("unsupported" in error for error in preflight(get_model("locator-fast"), device="cuda", root=tmp_path))

def test_models_resolve_outside_repo(tmp_path):
    model = get_model("whisper-medium")
    assert model_path(model, root=tmp_path).parent == tmp_path
    assert all(m.source for m in descriptors())


def test_snapshot_install_copies_hf_cache_symlinks(tmp_path, monkeypatch):
    """Hugging Face snapshots store regular assets as symlinks into blob cache."""
    import sys
    import types
    from types import SimpleNamespace

    model = get_model("whisper-small")
    blob_dir = tmp_path / "blobs"
    snap = tmp_path / "snapshot"
    blob_dir.mkdir()
    snap.mkdir()
    for name in model.required_assets:
        asset = blob_dir / name
        asset.write_bytes(("file-" + name).encode())
        (snap / name).symlink_to(asset)
    fake_hub = types.ModuleType("huggingface_hub")
    fake_hub.HfApi = lambda: SimpleNamespace(
        model_info=lambda *_args, **_kwargs: SimpleNamespace(sha="a" * 40)
    )
    fake_hub.snapshot_download = lambda **_kwargs: str(snap)
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake_hub)
    original_find_spec = catalog.importlib.util.find_spec
    monkeypatch.setattr(
        catalog.importlib.util, "find_spec",
        lambda name: object() if name == "huggingface_hub" else original_find_spec(name),
    )
    result = catalog.install(model, root=tmp_path / "models")
    assert result.is_dir()
    assert (result / "model.bin").is_file()
    assert not (result / "model.bin").is_symlink()
    assert catalog.installed(model, root=tmp_path / "models")
