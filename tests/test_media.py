from pathlib import Path

import pytest

from voice_studio.media import resolve_media_path


def test_resolve_media_path_accepts_string(tmp_path: Path):
    video = tmp_path / "sample.mp4"
    video.write_bytes(b"not-a-real-video")
    assert resolve_media_path(str(video)) == video


def test_resolve_media_path_accepts_gradio_like_dict(tmp_path: Path):
    video = tmp_path / "sample.webm"
    video.write_bytes(b"x")
    assert resolve_media_path({"path": str(video)}) == video


def test_resolve_media_path_rejects_missing_file(tmp_path: Path):
    with pytest.raises(ValueError, match="Không tìm thấy video"):
        resolve_media_path(str(tmp_path / "missing.mp4"))
