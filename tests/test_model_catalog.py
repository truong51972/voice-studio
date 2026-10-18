import json
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path

import pytest

from voice_studio import model_catalog
from voice_studio.model_catalog import CatalogError, catalog_directory, default_model, descriptors, load_catalog
from voice_studio.profiles import INFERENCE_PROFILES
from voice_studio.stt import STTOptions


@pytest.fixture
def catalog_copy(tmp_path):
    target = tmp_path / "catalog"
    shutil.copytree(catalog_directory(), target)
    return target


def test_all_current_models_and_defaults_come_from_catalog():
    assert len(descriptors()) == 7
    assert default_model("locator").id == "locator-fast"
    assert default_model("stt").id == STTOptions().model_id == "whisper-small"
    assert default_model("diarization").id == "pyannote-community-1"
    for model in descriptors("locator"):
        profile = INFERENCE_PROFILES[model.profile_key]
        assert profile.model_filename == model.required_assets[0]
        assert profile.model_sha256 == model.sha256
        assert profile.model_size == model.expected_size_bytes
        assert profile.default_threshold == model.inference_defaults.threshold == .60
    assert INFERENCE_PROFILES["fast"].model_size == 29_596_978
    assert INFERENCE_PROFILES["fast"].model_sha256 == "357a834f702b80161e5b981182c038e18553c1f2ca752ed6cec2052365d4129b"
    assert INFERENCE_PROFILES["accurate"].model_size == 71_441_526
    assert INFERENCE_PROFILES["accurate"].model_sha256 == "bf1a75b9930474cf3389ef415e6e5d38ca96fea4a3a00f7e301d080a58ee2239"


def test_locator_catalog_uses_english_names_and_descriptions():
    locator = {model.id: model for model in descriptors("locator")}
    assert locator["locator-fast"].label == "Fast · CAM++"
    assert locator["locator-accurate"].label == "Accurate · ERes2NetV2"
    for model in locator.values():
        # Retain the UI's separator (·), but prevent accented Vietnamese
        # phrases from leaking back into the English model catalog.
        for value in (model.label, model.description):
            assert value and not any(
                unicodedata.combining(char)
                for char in unicodedata.normalize("NFD", value)
            )


@pytest.mark.parametrize("change", [
    lambda data: data.update(schema_version=2),
    lambda data: data["models"][0].update(engine="os.system"),
    lambda data: data["models"][0].update(id="../escape"),
    lambda data: data["models"][0].update(required_assets=["../outside"]),
    lambda data: data["models"][0].update(required_assets=["C:\\outside"]),
    lambda data: data["models"][0].update(required_assets=["\\outside"]),
    lambda data: data["models"][0].update(required_assets=["/outside"]),
    lambda data: data["models"][0].update(task="diarization"),
    lambda data: data["models"][0].update(python_module="untrusted"),
    lambda data: data["models"][0].update(inference_defaults={"chunk_seconds": 0}),
    lambda data: data["models"][0].update(required_assets=["model.bin"]),
    lambda data: data["models"][0].update(download_urls=["file:///tmp/model"]),
    lambda data: data["models"][0].update(required_assets=["nul\u0000file"]),
    lambda data: data["models"][0].update(default=False),
    lambda data: data["models"].append(data["models"][1]),
])
def test_invalid_catalog_has_actionable_filename(catalog_copy, change):
    path = catalog_copy / "stt.json"
    data = json.loads(path.read_text())
    change(data)
    path.write_text(json.dumps(data))
    with pytest.raises(CatalogError, match="stt.json|duplicate"):
        load_catalog(catalog_copy)


def test_malformed_or_missing_catalog_is_explained(catalog_copy):
    path = catalog_copy / "diarization.json"
    path.write_text("{broken")
    with pytest.raises(CatalogError, match="diarization.json"):
        load_catalog(catalog_copy)
    path.unlink()
    with pytest.raises(CatalogError, match="diarization.json"):
        load_catalog(catalog_copy)


def test_compatible_model_can_be_added_as_json(catalog_copy):
    path = catalog_copy / "stt.json"
    data = json.loads(path.read_text())
    model = {**data["models"][0], "id": "another-whisper", "default": False}
    data["models"].append(model)
    path.write_text(json.dumps(data))
    loaded = load_catalog(catalog_copy)
    assert next(entry for entry in loaded if entry.id == model["id"]).engine == "faster-whisper"


def test_frozen_catalog_resolves_from_package_not_working_directory(tmp_path, monkeypatch):
    package = tmp_path / "_internal" / "voice_studio"
    destination = package / "configs" / "models"
    shutil.copytree(catalog_directory(), destination)
    monkeypatch.setattr(model_catalog, "__file__", str(package / "model_catalog.py"))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.chdir(tmp_path)
    assert catalog_directory() == destination
    assert len(load_catalog(catalog_directory())) == 7


def test_catalog_and_app_import_are_offline_and_do_not_load_backends(tmp_path):
    code = '''
import sys
from pathlib import Path
def no_network(*args, **kwargs):
    raise AssertionError("Startup attempted network access")
import socket
socket.create_connection = no_network
import voice_studio.app
from voice_studio.model_catalog import descriptors
assert len(descriptors()) == 7
assert not {"torch", "faster_whisper", "sherpa_onnx", "pyannote.audio"}.intersection(sys.modules)
assert not list(Path.cwd().iterdir())
'''
    subprocess.run([sys.executable, "-c", code], cwd=tmp_path, check=True)
