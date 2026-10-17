from __future__ import annotations

from pathlib import Path
from typing import TypeAlias

import soundfile as sf

import numpy as np
from scipy.signal import resample_poly

from .config import SAMPLE_RATE

GradioAudio: TypeAlias = tuple[int, np.ndarray] | str | Path | None


def to_mono_float32(audio: np.ndarray) -> np.ndarray:
    x = np.asarray(audio)
    if x.ndim == 2:
        # Gradio commonly returns shape [samples, channels].
        x = x.mean(axis=1)
    elif x.ndim != 1:
        raise ValueError("Audio phải là mono hoặc stereo.")

    if np.issubdtype(x.dtype, np.integer):
        info = np.iinfo(x.dtype)
        scale = float(max(abs(info.min), info.max))
        x = x.astype(np.float32) / scale
    else:
        x = x.astype(np.float32)

    if not np.all(np.isfinite(x)):
        raise ValueError("Audio chứa giá trị không hợp lệ.")

    peak = float(np.max(np.abs(x))) if x.size else 0.0
    if peak > 1.0:
        x = x / peak
    return np.ascontiguousarray(x, dtype=np.float32)


def resample_audio(samples: np.ndarray, source_rate: int, target_rate: int = SAMPLE_RATE) -> np.ndarray:
    if source_rate <= 0:
        raise ValueError("Sample rate không hợp lệ.")
    if source_rate == target_rate:
        return np.ascontiguousarray(samples, dtype=np.float32)

    # Rational polyphase resampling is fast enough for this CPU-first MVP.
    from math import gcd

    g = gcd(source_rate, target_rate)
    up = target_rate // g
    down = source_rate // g
    y = resample_poly(samples, up, down)
    return np.ascontiguousarray(y, dtype=np.float32)


def prepare_gradio_audio(value: GradioAudio, target_rate: int = SAMPLE_RATE) -> np.ndarray:
    if value is None:
        raise ValueError("Chưa có audio đầu vào.")

    if isinstance(value, (str, Path)):
        data, sample_rate = sf.read(str(value), always_2d=False)
    else:
        sample_rate, data = value

    samples = to_mono_float32(data)
    if samples.size == 0:
        raise ValueError("Audio rỗng.")
    return resample_audio(samples, int(sample_rate), target_rate)


def rms(samples: np.ndarray) -> float:
    if samples.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(samples, dtype=np.float64))))
