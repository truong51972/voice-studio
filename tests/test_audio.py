import numpy as np

from voice_studio.audio import resample_audio, to_mono_float32


def test_stereo_to_mono():
    stereo = np.column_stack([np.ones(100), np.zeros(100)]).astype(np.float32)
    mono = to_mono_float32(stereo)
    assert mono.shape == (100,)
    assert np.allclose(mono, 0.5)


def test_resample_changes_length():
    x = np.zeros(8_000, dtype=np.float32)
    y = resample_audio(x, 8_000, 16_000)
    assert 15_990 <= len(y) <= 16_010
