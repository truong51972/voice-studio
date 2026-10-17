"""Offline, chunked Whisper STT over FFmpeg decoded 16-kHz mono audio.

The source is never fully loaded into RAM. Timestamps are source-relative; no
overlapping chunk offsets are guessed. Silence filtering is optional.
"""
from __future__ import annotations

import subprocess
from dataclasses import asdict, dataclass
from math import isfinite
from pathlib import Path
from typing import Callable, Iterator

import numpy as np

from .media import ffmpeg_executable
from .model_registry import get_model, installed, model_path, preflight

SAMPLE_RATE = 16_000

@dataclass(frozen=True, slots=True)
class STTOptions:
    model_id: str = "whisper-small"
    language: str = "auto"
    vad: bool = True
    word_timestamps: bool = False
    chunk_seconds: int = 30
    device: str = "cpu"
    compute_type: str = "int8"

    def __post_init__(self):
        if self.language not in ("auto", "vi", "en"):
            raise ValueError("Language must be auto, vi or en")
        if not 5 <= self.chunk_seconds <= 60:
            raise ValueError("Chunk duration must be 5–60 seconds")
        if self.device not in ("cpu", "cuda"):
            raise ValueError("Unsupported STT device")

def _read_chunk(stream, samples_per_chunk: int) -> np.ndarray:
    required = samples_per_chunk * 4
    parts = []
    remaining = required
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

def stream_audio(path: str | Path, *, chunk_seconds: int = 30) -> Iterator[tuple[float, np.ndarray]]:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    command = [
        str(ffmpeg_executable()), "-hide_banner", "-loglevel", "error",
        "-i", str(path), "-map", "0:a:0", "-vn", "-ac", "1",
        "-ar", str(SAMPLE_RATE), "-f", "f32le", "-acodec", "pcm_f32le", "pipe:1",
    ]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    total_samples = 0
    try:
        assert process.stdout is not None
        while True:
            samples = _read_chunk(process.stdout, chunk_seconds * SAMPLE_RATE)
            if samples.size == 0:
                break
            if not np.all(np.isfinite(samples)):
                raise ValueError("Decoded audio has non-finite samples")
            yield total_samples / SAMPLE_RATE, samples
            total_samples += samples.size
        code = process.wait(timeout=20)
        if code:
            raise ValueError("FFmpeg failed to decode the media audio track")
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

def transcribe(
    media_path: str | Path,
    options: STTOptions,
    *,
    progress: Callable[[str], None] | None = None,
    engine=None,
    chunks=None,
) -> dict:
    model = get_model(options.model_id)
    if model.task != "stt":
        raise ValueError("Choose an STT model from Model Manager")
    if engine is None:
        problems = preflight(model, device=options.device)
        if problems:
            raise RuntimeError("; ".join(problems))
        try:
            from faster_whisper import WhisperModel
            engine = WhisperModel(
                str(model_path(model)), device=options.device,
                compute_type=options.compute_type, local_files_only=True,
            )
        except Exception as exc:
            raise RuntimeError(
                "Could not initialize offline Whisper runtime. Verify model files, CPU/CUDA DLLs and compute type."
            ) from exc
    if progress:
        progress("Model loaded · decoding audio in bounded chunks")
    segments: list[dict] = []
    duration = 0.0
    spoken_language = None
    iterator = chunks if chunks is not None else stream_audio(media_path, chunk_seconds=options.chunk_seconds)
    for offset, samples in iterator:
        if samples.size == 0:
            continue
        duration = max(duration, offset + samples.size / SAMPLE_RATE)
        # Preserve the actual silence/VAD option in the inference call; ignore
        # digital silence to avoid generating hallucinated text in silent chunks.
        rms = float(np.sqrt(np.mean(np.square(samples, dtype=np.float64))))
        if rms < 0.0003:
            if progress:
                progress(f"Skipping silence at {offset:.1f}s")
            continue
        if progress:
            progress(f"Transcribing {offset:.1f}–{duration:.1f}s")
        hypothesis, info = engine.transcribe(
            samples, language=None if options.language == "auto" else options.language,
            vad_filter=options.vad, word_timestamps=options.word_timestamps,
            beam_size=5,
        )
        spoken_language = getattr(info, "language", spoken_language)
        for segment in hypothesis:
            start = max(offset, offset + float(segment.start))
            end = min(duration, offset + float(segment.end))
            if not isfinite(start) or not isfinite(end) or end < start:
                raise ValueError("Whisper returned invalid segment timestamps")
            text = str(segment.text).strip()
            if not text:
                continue
            words = []
            if options.word_timestamps:
                for word in (getattr(segment, "words", None) or []):
                    words.append({
                        "start": offset + float(word.start),
                        "end": offset + float(word.end),
                        "text": str(word.word),
                    })
            segments.append({
                "id": f"s{len(segments)+1:06d}", "start": round(start, 3),
                "end": round(end, 3), "text": text, "words": words,
                "language": spoken_language, "speaker_id": None,
            })
    return {
        "kind": "stt", "schema": 1, "source": str(media_path),
        "model_id": options.model_id, "language": spoken_language,
        "options": asdict(options), "duration": round(duration, 3),
        "segments": segments,
    }
