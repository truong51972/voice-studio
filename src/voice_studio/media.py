from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import numpy as np

from .config import SAMPLE_RATE


VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}


def resolve_media_path(value: Any) -> Path:
    """Resolve the common filepath shapes returned by Gradio upload components."""
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

    cmd = [
        str(ffmpeg_executable()),
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(path),
        "-map",
        "0:a:0?",
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(int(sample_rate)),
        "-acodec",
        "pcm_f32le",
        "-f",
        "f32le",
        "pipe:1",
    ]
    try:
        proc = subprocess.run(
            cmd,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=900,
        )
    except subprocess.TimeoutExpired as exc:
        raise ValueError("Video quá dài hoặc giải mã audio bị timeout.") from exc

    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", errors="replace").strip()
        if len(detail) > 500:
            detail = detail[-500:]
        raise ValueError(
            "Không thể tách audio từ video. Video có thể không có audio stream hoặc file bị lỗi."
            + (f" Chi tiết: {detail}" if detail else "")
        )

    samples = np.frombuffer(proc.stdout, dtype="<f4").astype(np.float32, copy=True)
    if samples.size == 0:
        raise ValueError("Video không có audio stream có thể phân tích.")
    if not np.all(np.isfinite(samples)):
        raise ValueError("Audio giải mã từ video chứa dữ liệu không hợp lệ.")
    return np.ascontiguousarray(samples, dtype=np.float32)
