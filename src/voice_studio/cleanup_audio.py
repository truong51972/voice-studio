"""Optional FFmpeg denoise; source kept untouched for WER A/B comparisons."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .media import ffmpeg_executable


def denoise_media(source: str | Path, output: str | Path, *, noise_reduction: int = 12) -> Path:
    original = Path(source).resolve()
    destination = Path(output).resolve()
    if original == destination:
        raise ValueError("Audio enhancement must not overwrite original recording")
    if not original.is_file():
        raise FileNotFoundError(original)
    if destination.suffix.lower() != ".wav":
        raise ValueError("Output must be WAV")
    if destination.exists():
        raise FileExistsError(destination)
    if not 0 <= noise_reduction <= 24:
        raise ValueError("Noise reduction must be 0–24 dB")
    destination.parent.mkdir(parents=True, exist_ok=True)
    part = destination.with_suffix(".partial.wav")
    try:
        cmd = [
            str(ffmpeg_executable()), "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(original), "-vn", "-af", f"afftdn=nr={noise_reduction}",
            "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(part),
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=10800)
        if result.returncode or not part.is_file():
            raise RuntimeError("FFmpeg denoise failed: " + result.stderr.decode(errors="replace")[-400:])
        os.replace(part, destination)
        return destination
    finally:
        part.unlink(missing_ok=True)
