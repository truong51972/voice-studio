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


def diarize(path: str | Path, local_model_dir: str | Path, *, pipeline=None, work_directory: Path | None = None) -> dict:
    """Run a user-installed Community-1 from disk (no auto-download/token)."""
    # Disable usage telemetry before importing the optional local runtime.
    os.environ['PYANNOTE_METRICS_ENABLED'] = '0'
    os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
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
        try:
            pipeline = Pipeline.from_pretrained(str(model_dir))
        except Exception as exc:
            raise RuntimeError("Cannot load the local Community-1 model. Install a complete compatible "
                               "model with its local dependencies; no token/download is performed. " + str(exc)) from exc
    # Local temporary normalized waveform: no large PCM arrays over IPC.
    if work_directory is not None:
        work_directory.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="voice-studio-diar-", dir=work_directory) as work:
        wav = Path(work) / "audio.wav"
        command = [
            str(ffmpeg_executable()), "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(media), "-map", "0:a:0", "-vn", "-ac", "1", "-ar", "16000",
            "-c:a", "pcm_s16le", str(wav),
        ]
        process = subprocess.run(command, capture_output=True, timeout=10800)
        if process.returncode:
            raise RuntimeError("Could not decode audio for diarization: " + process.stderr.decode(errors="replace")[-400:])
        try:
            output = pipeline(str(wav))
        except Exception as exc:
            raise RuntimeError('Local diarization failed. Verify Community-1 assets, pyannote.audio 4 and its Torch/audio codec runtime. ' + str(exc)) from exc
    if not hasattr(output, "speaker_diarization"):
        raise RuntimeError("Incompatible diarization output. Install pyannote.audio 4 and Community-1 locally")
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


def dominant_speaker(start: float, end: float, turns: list[dict], *, min_coverage: float = .5) -> str | None:
    """Require coverage and a >1.25x lead; count each speaker's interval union."""
    intervals: dict[str, list[tuple[float, float]]] = {}
    for turn in turns:
        left, right = max(start, turn['start']), min(end, turn['end'])
        if right > left and turn.get('speaker_id'):
            intervals.setdefault(turn['speaker_id'], []).append((left, right))
    coverage = {}
    for speaker, spans in intervals.items():
        stop, total = start, 0.
        for left, right in sorted(spans):
            total += max(0., right - max(left, stop))
            stop = max(stop, right)
        coverage[speaker] = total
    ranked = sorted(coverage, key=lambda speaker: (-coverage[speaker], speaker))
    if ranked and coverage[ranked[0]] >= min_coverage * max(end - start, .001):
        if len(ranked) == 1 or coverage[ranked[0]] > coverage[ranked[1]] * 1.25:
            return ranked[0]
    return None


def attribute_segments(segments: list[dict], turns: list[dict], *, min_coverage: float = .2,
                       analysis_id: str | None = None) -> list[dict]:
    """Refresh automatic attribution; preserve human and untracked legacy labels.

    Does not alter original STT results. This is an editable proposal only.
    """
    result = []
    clean_turns = [turn for turn in turns if not turn.get('overlap')]
    for segment in segments:
        copy_segment = copy.deepcopy(segment)
        start, end = float(segment["start"]), float(segment["end"])
        origin = copy_segment.get('speaker_source')
        protected = origin == 'human' or (origin != 'diarization' and
                    (copy_segment.get('speaker_id') or copy_segment.get('speaker_review_required')))
        # Preserve a split's review flag until another analysis replaces it.
        same_analysis_warning = (copy_segment.get('speaker_review_required') and analysis_id is not None
                                 and copy_segment.get('speaker_analysis_id') == analysis_id)
        if protected or same_analysis_warning:
            result.append(copy_segment)
            continue
        speaker = dominant_speaker(start, end, clean_turns, min_coverage=min_coverage)
        copy_segment.update(speaker_id=speaker, speaker_source='diarization',
                            speaker_analysis_id=analysis_id, speaker_review_required=speaker is None)
        result.append(copy_segment)
    return result
