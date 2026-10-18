import faulthandler
import pytest

# Native Qt/FFmpeg shutdown failures can occur *after* pytest has printed
# "all passed"; keep the C-level traceback so a non-zero exit is diagnosable.
faulthandler.enable(all_threads=True)


@pytest.fixture(autouse=True)
def portable_test_home(tmp_path, monkeypatch):
    monkeypatch.setenv("VOICE_STUDIO_DATA_DIR", str(tmp_path / "app"))
    monkeypatch.delenv("VOICE_STUDIO_MODEL_DIR", raising=False)
