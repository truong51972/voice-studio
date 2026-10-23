import hashlib
import io
import json
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest

from voice_studio import model_service as module
from voice_studio.model_catalog import get_model
from voice_studio.model_service import Cancelled, MANIFEST, ModelService, download_file, safe_asset
from voice_studio.storage import atomic_json, read_json


@pytest.fixture
def service(tmp_path):
    return ModelService(tmp_path / "models", settings=tmp_path / "settings" / "models.json")


@pytest.fixture
def model():
    payload = b"test-weights"
    return get_model("locator-fast").model_copy(update={
        "required_assets": ("tiny.onnx",), "expected_size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(), "download_urls": ("https://example.invalid/model",),
    })


def managed(service, model):
    folder = service.owned_dir(model)
    folder.mkdir(parents=True)
    (folder / "tiny.onnx").write_bytes(b"test-weights")
    atomic_json(folder / MANIFEST, service._scan(model, folder, "sha256:" + model.sha256))
    return folder


def test_portable_paths_and_offline_initialization(tmp_path):
    service = ModelService()
    assert service.root.name == ".models"
    assert service.settings.parent.name == ".settings"
    assert not service.root.exists()
    assert not service.settings.exists()
    assert service.status(get_model("whisper-large-v3")).state == "Not installed"
    assert not service.root.exists()


def test_quick_status_does_not_hash_and_detects_changed_stats(service, model, monkeypatch):
    folder = managed(service, model)
    monkeypatch.setattr(module, "digest", lambda *args: pytest.fail("Status hashed weights"))
    assert service.status(model).state == "Installed"
    (folder / "tiny.onnx").write_bytes(b"changed")
    assert service.status(model).state == "Incomplete"


def test_explicit_verify_detects_same_size_tampering(service, model):
    folder = managed(service, model)
    (folder / "tiny.onnx").write_bytes(b"bad!-weights")
    with pytest.raises(ValueError, match="Integrity"):
        service.verify(model)
    assert not service.status(model).ready


@pytest.mark.parametrize("name", ["../escape", "C:/escape", "C:\\escape", "/etc/file", "x/../../escape", "file\0name"])
def test_reject_path_traversal(service, name):
    with pytest.raises(ValueError):
        safe_asset(service.root, name)


def test_reject_symlink_escape(service, tmp_path):
    service.root.mkdir()
    outside = tmp_path / "outside"
    outside.write_text("outside")
    try:
        (service.root / "link").symlink_to(outside)
    except OSError:
        pytest.skip("Symlinks require permission on Windows")
    with pytest.raises(ValueError, match="leaves"):
        safe_asset(service.root, "link")


def test_manifest_identity_and_publisher_metadata_are_checked(service, model):
    folder = managed(service, model)
    record = read_json(folder / MANIFEST)
    record["files"]["tiny.onnx"]["sha256"] = "a" * 64
    atomic_json(folder / MANIFEST, record)
    assert service.status(model).state == "Incomplete"


def test_import_unlink_never_deletes_external_weights(service, model, tmp_path):
    source = tmp_path / "external"
    source.mkdir()
    (source / "tiny.onnx").write_bytes(b"test-weights")
    service.import_local(model, source)
    assert service.path(model) == source / "tiny.onnx"
    assert service.status(model).verified
    assert not (source / MANIFEST).exists()
    service.remove(model)
    assert (source / "tiny.onnx").read_bytes() == b"test-weights"
    assert service.status(model).state == "Not installed"


def test_storage_switch_preserves_old_weights_and_projects(service, model, tmp_path):
    folder = managed(service, model)
    projects = tmp_path / "app" / ".projects"
    projects.mkdir(parents=True)
    (projects / "keep").write_text("review")
    service.set_storage(tmp_path / "elsewhere")
    assert (folder / "tiny.onnx").exists()
    assert (projects / "keep").read_text() == "review"
    assert ModelService(settings=service.settings).root == service.root


def test_in_use_model_cannot_be_removed_or_repaired(service, model):
    managed(service, model)
    with service.use(model):
        assert service.busy(model)
        with pytest.raises(RuntimeError, match="in use"):
            service.remove(model)
        with pytest.raises(RuntimeError, match="in use"):
            service.install(model)
    assert not service.busy(model)


def test_ready_runs_isolated_probe_and_preflight_then_accepts(service, model, monkeypatch):
    managed(service, model)
    assert service.preflight(model)
    calls = []
    def popen(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(poll=lambda: 0, returncode=0)
    monkeypatch.setattr(module.subprocess, "Popen", popen)
    service.ready(model)
    assert service.status(model).ready
    assert not service.preflight(model)
    assert calls[0][1]["env"]["HF_HUB_OFFLINE"] == "1"
    assert "voice_studio.model_backends" in calls[0][0]


def test_failed_probe_never_marks_ready(service, model, monkeypatch):
    managed(service, model)
    monkeypatch.setattr(module.subprocess, "Popen", lambda *a, **k: SimpleNamespace(poll=lambda: 1, returncode=1, kill=lambda: None, wait=lambda: None))
    with pytest.raises(RuntimeError, match="subprocess failed"):
        service.ready(model)
    assert not service.status(model).ready
    assert "subprocess failed" in service.status(model).detail


def test_cancelled_install_preserves_previous_model(service, model, monkeypatch):
    folder = managed(service, model)
    def cancel_download(*args, **kwargs):
        raise Cancelled("stopped")
    monkeypatch.setattr(module, "download_file", cancel_download)
    with pytest.raises(Cancelled):
        service.install(model)
    assert (folder / "tiny.onnx").read_bytes() == b"test-weights"
    assert service.status(model).state == "Installed"


def test_install_atomic_promotion_and_repair(service, model, monkeypatch):
    def download(_urls, path, *_args, **kwargs):
        path.write_bytes(b"test-weights")
    monkeypatch.setattr(module, "download_file", download)
    result = service.install(model)
    assert result.read_bytes() == b"test-weights"
    result.write_bytes(b"corrupt")
    assert service.status(model).state == "Incomplete"
    service.install(model)
    assert service.status(model).state == "Installed"
    assert service._record(model)["resolved_revision"].startswith("sha256:")


def test_gated_model_never_downloads(service, monkeypatch):
    monkeypatch.setattr(module, "urlopen", lambda *a, **k: pytest.fail("Gated access was bypassed"))
    with pytest.raises(ValueError, match="upstream"):
        service.install(get_model("pyannote-community-1"))


class Response(io.BytesIO):
    def __init__(self, payload, status=200, headers=None):
        super().__init__(payload)
        self.status, self.headers = status, headers or {}


@pytest.mark.parametrize("range_supported", [True, False])
def test_stream_resume_and_servers_ignoring_range(tmp_path, monkeypatch, range_supported):
    payload = b"abcdefghijklmn"
    target = tmp_path / "model"
    target.with_name("model.part").write_bytes(payload[:4])
    def serve(request, **kwargs):
        assert request.headers["Range"] == "bytes=4-"
        return Response(payload[4:], 206, {"Content-Range": "bytes 4-13/14"}) if range_supported else Response(payload)
    monkeypatch.setattr(module, "urlopen", serve)
    download_file(["https://example.invalid/model"], target, len(payload), hashlib.sha256(payload).hexdigest())
    assert target.read_bytes() == payload
    assert not target.with_name("model.part").exists()


def test_cancel_download_retains_partial_for_retry(tmp_path, monkeypatch):
    payload = b"x" * (2**20 + 2)
    target = tmp_path / "model"
    cancel = Event()
    monkeypatch.setattr(module, "urlopen", lambda *a, **k: Response(payload))
    with pytest.raises(Cancelled):
        download_file(["https://example.invalid/model"], target, len(payload), None, cancel=cancel, progress=lambda *a: cancel.set())
    assert not target.exists()
    assert target.with_name("model.part").stat().st_size == 2**20


def test_source_fallback_does_not_promote_wrong_hash(tmp_path, monkeypatch):
    target = tmp_path / "model"
    calls = []
    def serve(request, **kwargs):
        calls.append(request.full_url)
        return Response(b"bad" if request.full_url.endswith("bad") else b"yes")
    monkeypatch.setattr(module, "urlopen", serve)
    download_file(["https://example.invalid/bad", "https://example.invalid/good"], target, 3, hashlib.sha256(b"yes").hexdigest())
    assert target.read_bytes() == b"yes"
    assert calls[-1].endswith("good")


def test_complete_community_folder_validation(service, tmp_path):
    model = get_model("pyannote-community-1")
    folder = tmp_path / "community"
    folder.mkdir()
    (folder / "config.yaml").write_text("pipeline:\n  name: pyannote.audio.pipelines.SpeakerDiarization\n  params: {}\n")
    with pytest.raises(ValueError, match="Missing"):
        service.import_local(model, folder)
    for name in model.required_assets[1:]:
        path = folder / name
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(b"upstream fixture")
    service.import_local(model, folder)
    assert service.status(model).state == "Installed"
    (folder / "config.yaml").write_text("pipeline:\n  name: arbitrary.module.Class\n")
    with pytest.raises(ValueError, match="Only"):
        service.import_local(model, folder)


def test_unsafe_managed_symlink_is_incomplete_instead_of_crashing_refresh(service, model, tmp_path):
    """Status is a read-only UI query; install/remove must still reject escapes."""
    outside = tmp_path / "external"
    outside.mkdir()
    category = service.root / "speaker_matching"
    category.mkdir(parents=True)
    try:
        (category / model.id).symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Directory symlinks require elevated permissions on this Windows host")
    status = service.status(model)
    assert status.state == "Incomplete"
    assert "symlink" in status.detail
    assert status.path == category / model.id / "tiny.onnx"
    with pytest.raises(ValueError, match="symlink"):
        service.install(model)
    assert outside.is_dir()
