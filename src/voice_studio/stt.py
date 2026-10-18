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
from .storage import atomic_json, read_json

_STT_DEFAULT = default_model("stt")
_STT_PARAMETERS = _STT_DEFAULT.inference_defaults

SAMPLE_RATE = 16_000
_TIMESTAMP_DIGITS = 3


def _bounded_times(start: float, end: float, chunk_length: float) -> tuple[float, float] | None:
    """Map local Whisper timestamps into a valid, millisecond-resolution cue.

    Faster-Whisper timestamps are estimates and can fall just outside a 30s
    inference window, especially at VAD boundaries. Invalid/outside cues are
    dropped rather than corrupting the complete transcription.
    """
    if not all(isfinite(v) for v in (start, end, chunk_length)):
        return None
    if chunk_length <= 0 or end <= start:
        return None
    clipped_start = min(chunk_length, max(0., start))
    clipped_end = min(chunk_length, max(0., end))
    a, b = round(clipped_start, _TIMESTAMP_DIGITS), round(clipped_end, _TIMESTAMP_DIGITS)
    return (a, b) if b > a else None


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
    checkpoint_path: str | Path | None = None,
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
    warnings: list[str] = []
    warning_count = 0
    signature = {"source": str(media_path), "options": asdict(options)}
    checkpoint = Path(checkpoint_path) if checkpoint_path is not None else None

    # Only an exactly matching source/options snapshot may resume. The caller
    # also binds checkpoint filenames to a source fingerprint and model revision.
    if checkpoint is not None and checkpoint.is_file():
        try:
            saved = read_json(checkpoint)
            if saved.get("signature") == signature and isinstance(saved.get("segments"), list):
                last = float(saved["processed_seconds"])
                if isfinite(last) and last >= 0:
                    processed = duration = last
                    segments = list(saved["segments"])
                    spoken_language = saved.get("language")
                    warnings = list(saved.get("warnings", []))[:20]
                    warning_count = int(saved.get("warning_count", 0))
                    report("Resuming from saved audio", processed)
        except (OSError, ValueError, KeyError, TypeError):
            # A broken checkpoint never prevents a fresh transcription.
            pass

    def warn(message: str) -> None:
        nonlocal warning_count
        warning_count += 1
        if len(warnings) < 20:
            warnings.append(message)

    def save_checkpoint() -> None:
        if checkpoint is not None:
            atomic_json(checkpoint, {
                "schema": 1, "signature": signature,
                "processed_seconds": round(processed, 6),
                "segments": segments, "language": spoken_language,
                "warnings": warnings, "warning_count": warning_count,
            })

    iterator = chunks if chunks is not None else stream_audio(media_path, chunk_seconds=options.chunk_seconds)
    for offset, samples in iterator:
        if samples.size == 0:
            continue
        chunk_end = offset + samples.size / SAMPLE_RATE
        if chunk_end <= processed + 0.000001:
            # Re-decoding the source remains bounded; this avoids recomputing
            # already persisted chunks without relying on FFmpeg seek precision.
            report("Resuming from saved audio", processed)
            continue
        duration = max(duration, chunk_end)
        # Preserve the actual silence/VAD option in the inference call; ignore
        # digital silence to avoid generating hallucinated text in silent chunks.
        rms = float(np.sqrt(np.mean(np.square(samples, dtype=np.float64))))
        if rms < 0.0003:
            processed = max(processed, duration)
            save_checkpoint()
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
            try:
                raw_start, raw_end = float(segment.start), float(segment.end)
            except (TypeError, ValueError, OverflowError):
                warn(f"Chunk {offset:.3f}s: non-numeric segment timestamps")
                continue
            times = _bounded_times(raw_start, raw_end, samples.size / SAMPLE_RATE)
            if times is None:
                warn(f"Chunk {offset:.3f}s: ignored segment [{raw_start!r}, {raw_end!r}]")
                continue
            text = str(segment.text).strip()
            if not text:
                continue
            start, end = round(offset + times[0], 3), round(offset + times[1], 3)
            words = []
            if options.word_timestamps:
                for word in (getattr(segment, "words", None) or []):
                    try:
                        word_times = _bounded_times(float(word.start), float(word.end), samples.size / SAMPLE_RATE)
                    except (TypeError, ValueError, OverflowError):
                        word_times = None
                    if word_times is None:
                        warn(f"Chunk {offset:.3f}s: ignored invalid word timestamp")
                        continue
                    word_start = round(offset + word_times[0], 3)
                    word_end = round(offset + word_times[1], 3)
                    # Word cues must not outlive their parent subtitle.
                    word_start = max(start, word_start)
                    word_end = min(end, word_end)
                    if word_end <= word_start:
                        continue
                    words.append({"start": word_start, "end": word_end, "text": str(word.word)})
            segments.append({
                "id": f"s{len(segments)+1:06d}", "start": start,
                "end": end, "text": text, "words": words,
                "language": spoken_language, "speaker_id": None,
            })
        # faster-whisper returns lazy segments: only completed consumption counts.
        processed = max(processed, duration)
        save_checkpoint()
        report("Audio processed", processed)
    report("Finalizing transcript", processed)
    return {
        "kind": "stt", "schema": 1, "source": str(media_path),
        "model_id": options.model_id, "language": spoken_language,
        "options": asdict(options), "duration": round(duration, 3),
        "segments": segments, "warning_count": warning_count, "warnings": warnings,
    }
