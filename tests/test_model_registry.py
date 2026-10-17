import pytest

from voice_studio.model_registry import descriptors, get_model, model_path, preflight, installed


def test_catalog_is_task_aware_and_preserves_locator_checksums():
    assert len(descriptors("locator")) == 2
    assert len(descriptors("stt")) == 4
    assert len(descriptors("diarization")) == 1
    assert get_model("locator-fast").sha256 is not None
    with pytest.raises(KeyError):
        get_model("unknown")


def test_missing_models_have_gui_recovery(tmp_path):
    assert not installed(get_model("whisper-large-v3"), tmp_path)
    errors = preflight(get_model("whisper-large-v3"), root=tmp_path)
    assert any("not installed" in error and "Settings → Models" in error for error in errors)
    assert any("CUDA" in error for error in preflight(get_model("whisper-small"), device="cuda", root=tmp_path))


def test_models_resolve_in_portable_categories(tmp_path):
    assert model_path(get_model("whisper-medium"), tmp_path) == tmp_path / "stt" / "whisper-medium"
    assert model_path(get_model("locator-fast"), tmp_path).parent == tmp_path / "speaker_matching" / "locator-fast"
