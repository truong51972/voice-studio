from pathlib import Path

import pytest
import numpy as np
import soundfile as sf
import subprocess

from voice_studio.media import decode_audio, ffmpeg_executable, resolve_media_path, stream_audio


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


@pytest.fixture
def aac_media(tmp_path):
    rate = 16000
    time = np.arange(rate * 2) / rate
    samples = np.concatenate([.2 * np.sin(2 * np.pi * tone * time) for tone in (220, 880)])
    wav = tmp_path / "tones.wav"
    sf.write(wav, samples, rate)
    path = tmp_path / "tones.m4a"
    subprocess.run([str(ffmpeg_executable()), "-nostdin", "-v", "error", "-i", str(wav),
                    "-c:a", "aac", str(path)], check=True, capture_output=True)
    return path


def test_real_aac_m4a_decodes_for_locator_and_stt(aac_media):
    from voice_studio.audio import prepare_audio
    from voice_studio.stt import stream_audio as stt_stream_audio
    audio = prepare_audio(aac_media)
    assert audio.dtype == np.float32
    assert 64000 <= len(audio) < 66000
    assert np.sqrt(np.mean(audio ** 2)) > .1
    chunks = list(stt_stream_audio(aac_media, chunk_seconds=1))
    assert all(len(samples) <= 16000 for _, samples in chunks)
    assert [offset for offset, _ in chunks][:4] == [0., 1., 2., 3.]
    np.testing.assert_array_equal(np.concatenate([samples for _, samples in chunks]), audio)


def test_region_decoding_seeks_source_and_limits_output(aac_media):
    samples = decode_audio(aac_media, start=2.25, end=3.25)
    assert len(samples) == 16000
    frequency = np.fft.rfftfreq(len(samples), 1 / 16000)[np.abs(np.fft.rfft(samples)).argmax()]
    assert frequency == pytest.approx(880, abs=2)
    assert next(stream_audio(aac_media, start=2.25, end=3.25))[0] == 2.25


@pytest.mark.parametrize("extension", ["wav", "flac"])
def test_wav_flac_and_resampling_still_work(tmp_path, extension):
    from voice_studio.audio import prepare_audio
    path = tmp_path / f"source.{extension}"
    sf.write(path, np.full(8000, .25, dtype=np.float32), 8000)
    audio = prepare_audio(path)
    assert len(audio) == 16000
    assert np.mean(audio) == pytest.approx(.25, abs=.001)


@pytest.mark.parametrize("options", [
    {"start": -1}, {"start": float("nan")}, {"end": float("inf")},
    {"start": 2., "end": 1.}, {"end": 0.}, {"chunk_seconds": 0},
])
def test_invalid_decode_regions_are_rejected(aac_media, options):
    with pytest.raises(ValueError):
        list(stream_audio(aac_media, **options))


def test_bad_media_and_outside_source_have_actionable_errors(tmp_path, aac_media):
    corrupt = tmp_path / "bad.m4a"
    corrupt.write_bytes(b"not AAC audio")
    with pytest.raises(ValueError, match="audio stream"):
        decode_audio(corrupt)
    with pytest.raises(ValueError, match="selected interval"):
        decode_audio(aac_media, start=100., end=101.)


def test_closing_stream_terminates_decoder(aac_media, monkeypatch):
    import voice_studio.media as media
    original = media.subprocess.Popen
    processes = []
    def launch(*args, **kwargs):
        process = original(*args, **kwargs)
        processes.append(process)
        return process
    monkeypatch.setattr(media.subprocess, "Popen", launch)
    chunks = stream_audio(aac_media, chunk_seconds=1)
    next(chunks)
    chunks.close()
    assert processes[0].poll() is not None
    assert processes[0].stdout.closed
