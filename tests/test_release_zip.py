from pathlib import Path
import importlib.util

module_path = Path(__file__).resolve().parents[1] / "scripts" / "release_zip.py"
spec = importlib.util.spec_from_file_location("voice_studio_release_zip_test", module_path)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
pack, sha256 = module.pack, module.sha256

def test_release_zip_is_stable_and_has_checksum(tmp_path):
    dist = tmp_path / "dist" / "voice-studio"
    dist.mkdir(parents=True)
    (dist / "voice-studio.exe").write_bytes(b"exe-demo")
    sub = dist / "_internal"
    sub.mkdir()
    (sub / "library.dll").write_bytes(b"dll")
    output = tmp_path / "VoiceStudio-test-windows-x64.zip"
    pack(dist, output)
    first = sha256(output)
    archive, checksum = pack(dist, output)
    assert sha256(archive) == first
    assert first in checksum.read_text()
    from zipfile import ZipFile
    with ZipFile(archive) as z:
        assert "voice-studio/voice-studio.exe" in z.namelist()
        assert "voice-studio/_internal/library.dll" in z.namelist()
