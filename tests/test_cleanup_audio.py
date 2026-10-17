import pytest
from voice_studio.cleanup_audio import denoise_media

def test_denoise_does_not_overwrite_original(tmp_path):
    source = tmp_path / "audio.wav"
    source.write_bytes(b"not valid audio")
    with pytest.raises(ValueError):
        denoise_media(source, source)
    with pytest.raises(ValueError):
        denoise_media(source, tmp_path / "out.mp3")
    with pytest.raises(ValueError):
        denoise_media(source, tmp_path / "out.wav", noise_reduction=50)
    assert source.read_bytes() == b"not valid audio"
