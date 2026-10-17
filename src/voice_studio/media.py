from __future__ import annotations

import subprocess
import tempfile
from math import isfinite
from pathlib import Path
from typing import Any, Iterator

import numpy as np

from .config import SAMPLE_RATE


VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}


def resolve_media_path(value: Any) -> Path:
    """Resolve a local filepath from a path, file descriptor mapping or file-like object."""
    if value is None:
        raise ValueError("Chưa có video đầu vào.")

    if isinstance(value, (str, Path)):
        path = Path(value)
    elif isinstance(value, dict):
        raw = value.get("path") or value.get("name")
        if not raw:
            raise ValueError("Không xác định được đường dẫn video đã tải lên.")
        path = Path(raw)
    else:
        raw = getattr(value, "path", None) or getattr(value, "name", None)
        if not raw:
            raise ValueError("Định dạng dữ liệu video từ giao diện không được hỗ trợ.")
        path = Path(raw)

    if not path.is_file():
        raise ValueError(f"Không tìm thấy video đã tải lên: {path}")
    return path


def ffmpeg_executable() -> Path:
    """Return the ffmpeg binary shipped by imageio-ffmpeg.

    imageio-ffmpeg wheels include a platform-specific ffmpeg executable.  This
    keeps the packaged desktop build self-contained instead of depending on a
    system-wide ffmpeg installation.
    """
    try:
        import imageio_ffmpeg
    except ImportError as exc:
        raise RuntimeError(
            "Thiếu dependency imageio-ffmpeg để đọc video. Chạy `uv sync --dev --refresh`."
        ) from exc

    path = Path(imageio_ffmpeg.get_ffmpeg_exe())
    if not path.is_file():
        raise RuntimeError(f"Không tìm thấy ffmpeg runtime đi kèm ứng dụng: {path}")
    return path


def extract_audio_from_video(value: Any, sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """Decode a video's audio stream directly to mono float32 PCM in memory."""
    path = resolve_media_path(value)
    if path.suffix.lower() not in VIDEO_EXTENSIONS:
        raise ValueError(
            "Định dạng video chưa được hỗ trợ. Hãy dùng MP4, MOV, MKV, WEBM, AVI hoặc M4V."
        )

    return decode_audio(path, sample_rate=sample_rate)


def _read_chunk(stream, samples_per_chunk: int) -> np.ndarray:
    remaining = samples_per_chunk * 4
    parts = []
    while remaining:
        fragment = stream.read(remaining)
        if not fragment:
            break
        parts.append(fragment)
        remaining -= len(fragment)
    raw = b"".join(parts)
    if len(raw) % 4:
        raise ValueError("FFmpeg produced a partial float32 frame")
    return np.frombuffer(raw, dtype="<f4").copy()


def stream_audio(
    path: str | Path, *, chunk_seconds: int = 30, sample_rate: int = SAMPLE_RATE,
    start: float = 0., end: float | None = None,
) -> Iterator[tuple[float, np.ndarray]]:
    """Decode bounded mono chunks; offsets stay relative to the original source.

    Input seeking plus an output duration bounds reference decoding without
    loading the recording before the selection. Closing the iterator kills FFmpeg.
    """
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    if not isinstance(chunk_seconds, int) or not 1 <= chunk_seconds <= 60:
        raise ValueError("Chunk duration must be 1–60 whole seconds")
    if not isinstance(sample_rate, int) or sample_rate <= 0:
        raise ValueError("Sample rate must be a positive integer")
    if not isfinite(start) or start < 0 or (end is not None and (not isfinite(end) or end <= start)):
        raise ValueError("Expected finite source interval 0 <= start < end")
    command = [str(ffmpeg_executable()), "-nostdin", "-hide_banner", "-loglevel", "error"]
    if start:
        command += ["-ss", str(start)]
    command += ["-i", str(path)]
    if end is not None:
        command += ["-t", str(end - start)]
    command += ["-map", "0:a:0", "-vn", "-ac", "1", "-ar", str(sample_rate),
                "-f", "f32le", "-acodec", "pcm_f32le", "pipe:1"]
    # A file avoids stderr pipe deadlocks on corrupt media; only the tail is read.
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=errors)
        total_samples = 0
        try:
            assert process.stdout is not None
            while True:
                samples = _read_chunk(process.stdout, chunk_seconds * sample_rate)
                if not samples.size:
                    break
                if not np.all(np.isfinite(samples)):
                    raise ValueError("Decoded audio has non-finite samples")
                yield start + total_samples / sample_rate, samples
                total_samples += samples.size
            code = process.wait(timeout=20)
            if code or not total_samples:
                errors.seek(0, 2)
                errors.seek(max(0, errors.tell() - 500))
                detail = errors.read().decode(errors="replace").strip()
                raise ValueError("FFmpeg could not decode an audio stream. Check the codec, "
                                 "source file and selected interval." + (f" Details: {detail}" if detail else ""))
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            if process.stdout is not None:
                process.stdout.close()


def decode_audio(
    path: str | Path, *, sample_rate: int = SAMPLE_RATE,
    start: float = 0., end: float | None = None,
) -> np.ndarray:
    """Collect a chosen region for existing array-based Locator callers.

    Long-running consumers should use stream_audio instead of collecting chunks.
    """
    return np.concatenate([samples for _, samples in stream_audio(
        path, sample_rate=sample_rate, start=start, end=end,
    )])
