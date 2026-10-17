"""Offline, chunked Whisper STT over FFmpeg decoded 16-kHz mono audio.

The source is never fully loaded into RAM. Timestamps are source-relative; no
overlapping chunk offsets are guessed. Silence filtering is optional.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from math import isfinite
import re
import subprocess
from pathlib import Path
from typing import Callable

import numpy as np

from .media import _read_chunk, stream_audio, ffmpeg_executable
from .model_registry import get_model, installed, model_path, preflight
from .model_catalog import default_model

_STT_DEFAULT = default_model("stt")
_STT_PARAMETERS = _STT_DEFAULT.inference_defaults

SAMPLE_RATE = 16_000

@dataclass(frozen=True, slots=True)
class STTOptions:
    model_id: str = _STT_DEFAULT.id
    language: str = _STT_PARAMETERS.language
    vad: bool = _STT_PARAMETERS.vad
    word_timestamps: bool = _STT_PARAMETERS.word_timestamps
    chunk_seconds: int = _STT_PARAMETERS.chunk_seconds
    beam_size: int = _STT_PARAMETERS.beam_size
    device: str = _STT_PARAMETERS.device
    compute_type: str = _STT_PARAMETERS.compute_type

    def __post_init__(self):
        if self.language not in ("auto", "vi", "en"):
            raise ValueError("Language must be auto, vi or en")
        if not 5 <= self.chunk_seconds <= 60:
            raise ValueError("Chunk duration must be 5–60 seconds")
        if not 1 <= self.beam_size <= 20:
            raise ValueError("Beam size must be 1–20")
        if self.device not in ("cpu", "cuda"):
            raise ValueError("Unsupported STT device")
        if self.compute_type not in ("int8", "float32", "float16", "int8_float16"):
            raise ValueError("Unsupported STT compute type")
        if self.device == "cuda" and self.compute_type not in ("float16", "int8_float16"):
            raise ValueError("CUDA STT requires float16 or int8_float16")

def transcribe(
    media_path: str | Path,
    options: STTOptions,
    *,
    progress: Callable[[str | dict], None] | None = None,
    engine=None,
    chunks=None,
    total_seconds: float | None = None,
) -> dict:
    model = get_model(options.model_id)
    if model.task != "stt":
        raise ValueError("Choose an STT model from Model Manager")
    # Project metadata is already validated at import. Standalone calls use a
    # bounded FFmpeg header probe, never a full decode or file hash.
    if total_seconds is None and chunks is None:
        try:
            result = subprocess.run(
                [str(ffmpeg_executable()), "-nostdin", "-hide_banner", "-i", str(media_path)],
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=20,
            )
            match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)",
                              result.stderr.decode(errors="replace"))
            if match:
                total_seconds = int(match[1]) * 3600 + int(match[2]) * 60 + float(match[3])
        except (OSError, subprocess.TimeoutExpired, ValueError):
            pass
    total_seconds = float(total_seconds) if total_seconds is not None else None
    if total_seconds is not None and (not isfinite(total_seconds) or total_seconds <= 0):
        total_seconds = None

    def report(stage: str, processed: float = 0.) -> None:
        if progress:
            progress({"stage": stage, "processed_seconds": round(max(0., processed), 3),
                      "total_seconds": total_seconds, "model": options.model_id,
                      "device": options.device})

    report("Loading STT model")
    if engine is None:
        problems = preflight(model, device=options.device, compute_type=options.compute_type)
        if problems:
            raise RuntimeError("; ".join(problems))
        try:
            if options.device == "cuda":
                from .model_backends import prepare_cuda_runtime
                prepare_cuda_runtime()
            from faster_whisper import WhisperModel
            engine = WhisperModel(
                str(model_path(model)), device=options.device,
                compute_type=options.compute_type, local_files_only=True,
            )
        except Exception as exc:
            raise RuntimeError(
                "Could not initialize offline Whisper runtime. Verify model files, CPU/CUDA DLLs and compute type."
            ) from exc
    report("Decoding audio in bounded chunks")
    segments: list[dict] = []
    duration = 0.0
    processed = 0.0
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
            processed = max(processed, duration)
            report("Skipping silence", processed)
            continue
        report(f"Transcribing {offset:.1f}–{duration:.1f}s", processed)
        hypothesis, info = engine.transcribe(
            samples, language=None if options.language == "auto" else options.language,
            vad_filter=options.vad, word_timestamps=options.word_timestamps,
            beam_size=options.beam_size,
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
        # faster-whisper returns lazy segments: only completed consumption counts.
        processed = max(processed, duration)
        report("Audio processed", processed)
    report("Finalizing transcript", processed)
    return {
        "kind": "stt", "schema": 1, "source": str(media_path),
        "model_id": options.model_id, "language": spoken_language,
        "options": asdict(options), "duration": round(duration, 3),
        "segments": segments,
    }
