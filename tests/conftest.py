import pytest


@pytest.fixture(autouse=True)
def portable_test_home(tmp_path, monkeypatch):
    monkeypatch.setenv("VOICE_STUDIO_DATA_DIR", str(tmp_path / "app"))
    monkeypatch.delenv("VOICE_STUDIO_MODEL_DIR", raising=False)
