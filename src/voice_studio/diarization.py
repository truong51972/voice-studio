"""Optional offline anonymous-speaker diarization and conservative STT alignment."""
from __future__ import annotations

import copy
import os
import subprocess
import tempfile
from pathlib import Path

from .media import ffmpeg_executable


def _speaker_turns(output, *, exclusive: bool = False, label_map: dict | None = None) -> list[dict]:
    annotation = getattr(output, "exclusive_speaker_diarization", None) if exclusive else None
    if annotation is None:
        annotation = output.speaker_diarization
    raw = []
    for segment, _track, label in annotation.itertracks(yield_label=True):
        start, end = float(segment.start), float(segment.end)
        if start < 0 or end <= start:
            continue
        raw.append((start, end, str(label)))
    raw.sort(key=lambda p: (p[0], p[1]))
    if label_map is None:
        label_map = {}
    for _, _, label in raw:
        if label not in label_map:
            label_map[label] = f"Speaker {len(label_map)+1}"
    turns = []
    for start, end, label in raw:
        overlap = any(
            other[0] < end and other[1] > start and other[2] != label
            for other in raw
        )
        turns.append({
            "start": start, "end": end,
            "speaker_id": label_map[label],
            "cluster_id": label,
            # Community-1 clustering is not a verified identity or probability.
            "confidence": None,
            "overlap": overlap,
        })
    return turns


def diarize(path: str | Path, local_model_dir: str | Path, *, pipeline=None) -> dict:
    """Run a user-installed Community-1 from disk (no auto-download/token)."""
    media = Path(path)
    if not media.is_file():
        raise FileNotFoundError(media)
    model_dir = Path(local_model_dir)
    if pipeline is None:
        if not model_dir.is_dir() or not (model_dir / "config.yaml").is_file():
            raise FileNotFoundError("Install a complete Community-1 model folder locally first.")
        os.environ["HF_HUB_OFFLINE"] = "1"
        try:
            from pyannote.audio import Pipeline
        except ImportError as exc:
            raise RuntimeError("Install optional pyannote audio runtime: uv sync --extra diarization") from exc
        pipeline = Pipeline.from_pretrained(str(model_dir))
    # Local temporary normalized waveform: no large PCM arrays over IPC.
    with tempfile.TemporaryDirectory(prefix="voice-studio-diar-") as work:
        wav = Path(work) / "audio.wav"
        command = [
            str(ffmpeg_executable()), "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(media), "-map", "0:a:0", "-vn", "-ac", "1", "-ar", "16000",
            "-c:a", "pcm_s16le", str(wav),
        ]
        process = subprocess.run(command, capture_output=True, timeout=10800)
        if process.returncode:
            raise RuntimeError("Could not decode audio for diarization: " + process.stderr.decode(errors="replace")[-400:])
        output = pipeline(str(wav))
    labels = {}
    turns = _speaker_turns(output, label_map=labels)
    exclusive_turns = _speaker_turns(output, exclusive=True, label_map=labels)
    return {
        "kind": "diarization", "source": str(media),
        "model": "pyannote-community-1",
        "speakers": sorted({t["speaker_id"] for t in turns}),
        "turns": turns,
        "exclusive_turns": exclusive_turns,
    }


def attribute_segments(segments: list[dict], turns: list[dict], *, min_coverage: float = .2) -> list[dict]:
    """Anonymous overlap attribution; uncertain ties remain unassigned.

    Does not alter original STT results. This is an editable proposal only.
    """
    result = []
    for segment in segments:
        copy_segment = copy.deepcopy(segment)
        start, end = float(segment["start"]), float(segment["end"])
        if copy_segment.get("speaker_id"):
            result.append(copy_segment)
            continue
        overlaps: dict[str, float] = {}
        for turn in turns:
            if turn.get("overlap"):
                continue  # ambiguous overlap is left to manual review
            shared = max(0.0, min(end, turn["end"]) - max(start, turn["start"]))
            if shared:
                label = str(turn["speaker_id"])
                overlaps[label] = overlaps.get(label, 0) + shared
        ranked = sorted(overlaps.items(), key=lambda x: x[1], reverse=True)
        length = max(end - start, 0.001)
        if ranked and ranked[0][1] / length >= min_coverage:
            if len(ranked) == 1 or ranked[0][1] > ranked[1][1] * 1.25:
                copy_segment["speaker_id"] = ranked[0][0]
        result.append(copy_segment)
    return result
