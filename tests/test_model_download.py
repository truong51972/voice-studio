from __future__ import annotations

import hashlib
from dataclasses import replace


def _load_downloader():
    from voice_studio import model_download
    return model_download


def _test_profile(module, payload: bytes, filename: str = "model.onnx"):
    base = next(iter(module.INFERENCE_PROFILES.values()))
    return replace(
        base,
        key="test",
        label="Test profile",
        model_filename=filename,
        model_size=len(payload),
        model_sha256=hashlib.sha256(payload).hexdigest(),
        download_urls=("https://example.invalid/model.onnx",),
    )


def test_validate_model_checks_exact_size_and_sha256(tmp_path):
    module = _load_downloader()
    payload = b"voice-studio-model-test" * 100
    model = tmp_path / "model.onnx"
    model.write_bytes(payload)
    profile = _test_profile(module, payload)

    assert module.validate_model(model, profile, verbose=False)

    model.write_bytes(payload[:-1])
    assert not module.validate_model(model, profile, verbose=False)


def test_download_once_streams_local_source(tmp_path, monkeypatch):
    module = _load_downloader()
    payload = (b"0123456789abcdef" * 4096) + b"done"
    source = tmp_path / "source.onnx"
    part = tmp_path / "download.onnx.part"
    source.write_bytes(payload)

    monkeypatch.setattr(module, "CHUNK_SIZE", 4096)
    module._download_once(source.as_uri(), part, len(payload))

    assert part.read_bytes() == payload


def test_ensure_model_repairs_corrupt_final_model(tmp_path, monkeypatch):
    module = _load_downloader()
    payload = b"correct-model" * 64
    profile = _test_profile(module, payload)
    model_dir = tmp_path / "models"
    model_dir.mkdir()
    destination = model_dir / profile.model_filename
    destination.write_bytes(b"corrupt-but-present")

    monkeypatch.setattr(module, "MODEL_DIR", model_dir)

    def fake_download(selected_profile, path):
        assert selected_profile == profile
        assert path == destination
        path.write_bytes(payload)

    monkeypatch.setattr(module, "_download_model", fake_download)
    module.ensure_model(profile)

    assert destination.read_bytes() == payload
    assert module.validate_model(destination, profile, verbose=False)


def test_ensure_model_preserves_interrupted_download_for_resume(tmp_path, monkeypatch):
    module = _load_downloader()
    full_payload = b"0123456789" * 100
    partial_payload = full_payload[:400]
    profile = _test_profile(module, full_payload)
    model_dir = tmp_path / "models"
    model_dir.mkdir()
    destination = model_dir / profile.model_filename
    destination.write_bytes(partial_payload)

    monkeypatch.setattr(module, "MODEL_DIR", model_dir)
    observed = {}

    def fake_download(selected_profile, path):
        assert selected_profile == profile
        part = path.with_suffix(path.suffix + ".part")
        observed["part"] = part.read_bytes()
        path.write_bytes(full_payload)
        part.unlink(missing_ok=True)

    monkeypatch.setattr(module, "_download_model", fake_download)
    module.ensure_model(profile)

    assert observed["part"] == partial_payload
    assert destination.read_bytes() == full_payload


def test_main_ensures_every_registered_profile(monkeypatch):
    module = _load_downloader()
    profiles = list(module.INFERENCE_PROFILES.values())
    observed = []
    monkeypatch.setattr(module, "ensure_model", observed.append)

    module.main()

    assert observed == profiles
