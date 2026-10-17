"""Project workers: all media hashing, decoding and models stay out of Qt."""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import asdict
from pathlib import Path

import numpy as np

from .audio import rms
from .config import HOP_SECONDS, MIN_WINDOW_RMS, SAMPLE_RATE, WINDOW_SECONDS
from .media import ffmpeg_executable, stream_audio
from .projects import _atomic_write, _cache_key, _hash_file


def probe_media(path: str | Path) -> dict:
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Source media missing: {path}")
    process = subprocess.run([str(ffmpeg_executable()), "-nostdin", "-hide_banner", "-i", str(path)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=30)
    detail = process.stderr.decode(errors="replace")
    duration = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", detail)
    if not duration or not re.search(r"Stream .*Audio:", detail):
        raise ValueError(f"Cannot read an audio stream/duration from {path.name}. "
                         "Check that the file is complete and its codec is supported by FFmpeg. " + detail[-400:])
    seconds = int(duration[1]) * 3600 + int(duration[2]) * 60 + float(duration[3])
    if seconds <= 0:
        raise ValueError("Source duration must be positive")
    video = any("Video:" in line and "attached pic" not in line for line in detail.splitlines() if "Stream " in line)
    fingerprint = _hash_file(path)
    stat = path.stat()
    return {"source": str(path), "fingerprint": fingerprint, "bytes": stat.st_size,
            "mtime_ns": stat.st_mtime_ns, "duration": seconds, "kind": "video" if video else "audio"}


def waveform_path(directory: Path, fingerprint: str) -> Path:
    return directory / "cache" / f"waveform-v1-{fingerprint}.json"


def cache_waveform(path: str, directory: Path, fingerprint: str) -> None:
    destination = waveform_path(directory, fingerprint)
    if destination.is_file():
        return
    peaks = []
    for _, chunk in stream_audio(path, sample_rate=8000, chunk_seconds=10):
        full = len(chunk) // 800
        peaks.extend(np.max(np.abs(chunk[:full * 800].reshape(-1, 800)), axis=1).round(4).tolist())
        if full * 800 < len(chunk):
            peaks.append(round(float(np.max(np.abs(chunk[full * 800:]))), 4))
    _atomic_write(destination, {"seconds_per_peak": .1, "peaks": peaks})


def _embedder(profile: str):
    from .embedding import SpeakerEmbedder
    from .profiles import get_inference_profile
    descriptor = get_inference_profile(profile)
    if not descriptor.model_path.is_file():
        raise ValueError(f"Install the {descriptor.label} speaker model in Model Manager first")
    revision = _hash_file(descriptor.model_path)
    if revision != descriptor.model_sha256:
        raise ValueError("Speaker model checksum mismatch. Verify/reinstall it in Model Manager")
    return SpeakerEmbedder(descriptor.model_path, descriptor.num_threads), revision


def _unit(vector):
    vector = np.asarray(vector, dtype=np.float32)
    length = np.linalg.norm(vector)
    if not np.isfinite(length) or length < 1e-10:
        raise ValueError("Could not create a usable embedding; select clean speech")
    return vector / length


def reference_embedding(region: dict, source: dict, directory: Path, embedder, revision: str) -> np.ndarray:
    start, end = float(region["start"]), float(region["end"])
    if region["fingerprint"] != source["fingerprint"]:
        raise ValueError("Reference media changed. Select a new source interval")
    if not 0 <= start < end <= source["duration"] or end - start < 1.:
        raise ValueError("Select at least 1 second of clean single-speaker speech inside the source")
    key = _cache_key(source["fingerprint"], {"start": start, "end": end, "model_revision": revision})
    cache = directory / "cache" / f"embedding-{key}.json"
    if cache.is_file():
        return _unit(json.loads(cache.read_text())["embedding"])
    vectors = []
    total_energy = total_samples = 0.
    for _, chunk in stream_audio(source["source"], start=start, end=end, chunk_seconds=10):
        total_energy += float(np.sum(chunk.astype(np.float64) ** 2))
        total_samples += len(chunk)
        if len(chunk) >= SAMPLE_RATE and rms(chunk) >= MIN_WINDOW_RMS:
            vectors.append(embedder.compute(chunk))
    if not vectors or (total_energy / max(1, total_samples)) ** .5 < MIN_WINDOW_RMS:
        raise ValueError("Reference is silent/too quiet or too short. Select clear speech, usually 3–10 seconds")
    vector = _unit(np.mean(vectors, axis=0))
    _atomic_write(cache, {"embedding": vector.tolist(), "fingerprint": source["fingerprint"],
                          "start": start, "end": end, "model_revision": revision})
    return vector


def stream_windows(path: str):
    """Same 2.5s/0.5s grid and final window as Locator, with bounded PCM."""
    window, hop = round(WINDOW_SECONDS * SAMPLE_RATE), round(HOP_SECONDS * SAMPLE_RATE)
    buffer = np.empty(0, dtype=np.float32)
    base = next_start = total = 0
    last_start = -1
    for _, chunk in stream_audio(path, chunk_seconds=30):
        buffer = np.concatenate((buffer, chunk))
        total += len(chunk)
        while next_start + window <= total:
            relative = next_start - base
            yield next_start / SAMPLE_RATE, (next_start + window) / SAMPLE_RATE, buffer[relative:relative + window]
            last_start = next_start
            next_start += hop
        keep_from = max(base, total - window)
        buffer = buffer[keep_from - base:].copy()
        base = keep_from
    final_start = max(0, total - window)
    if total and final_start > last_start:
        yield final_start / SAMPLE_RATE, total / SAMPLE_RATE, buffer[final_start - base:]


def match_references(inputs: dict, embedder, revision: str, progress) -> dict:
    from .localization import WindowScore, merge_matches
    from .similarity import moving_average
    directory = Path(inputs["project_directory"])
    sources = {m["id"]: m for m in inputs["media"]}
    references = {}
    for region in inputs["references"]:
        if region["state"] != "ready":
            continue
        source = sources[region["media_id"]]
        if _hash_file(Path(source["source"])) != source["fingerprint"]:
            raise ValueError("Reference source changed; relink/reselect it before matching")
        references.setdefault(region["speaker_id"], []).append(reference_embedding(region, source, directory, embedder, revision))
    if not references:
        raise ValueError("Add a clean manual reference and wait for its embedding before matching")
    vectors = {key: _unit(np.mean(values, axis=0)) for key, values in references.items()}
    raw = {key: [] for key in vectors}
    times = []
    for start, end, chunk in stream_windows(inputs["target_path"]):
        has_speech = rms(chunk) >= MIN_WINDOW_RMS
        vector = None
        if has_speech:
            try:
                vector = embedder.compute(chunk)
            except ValueError:
                has_speech = False
        for key, reference in vectors.items():
            raw[key].append(float(np.dot(reference, vector)) if vector is not None else 0.)
        times.append((start, end, has_speech))
        if len(times) % 100 == 0:
            progress(f"Matching source {end:.1f}s")
    duration = times[-1][1] if times else 0.
    results = []
    names = {s["id"]: s["name"] for s in inputs["speakers"]}
    for key, values in raw.items():
        smoothed = moving_average(np.asarray(values, dtype=np.float32), 3)
        scores = [WindowScore(start, end, (start + end) / 2, float(score), speech)
                  for (start, end, speech), score in zip(times, smoothed)]
        segments = merge_matches(scores, inputs["options"]["threshold"])
        matched = sum(s.end - s.start for s in segments)
        results.append({"key": key, "name": names[key], "scores": [asdict(s) for s in scores],
                        "segments": [asdict(s) for s in segments], "matched_duration": matched,
                        "coverage": 100 * matched / duration if duration else 0.,
                        "max_score": max(values) if values else None})
    return {"kind": "locator", "media_kind": inputs["media_kind"], "duration": duration,
            "profile": inputs["options"]["profile"], "threshold": inputs["options"]["threshold"],
            "model_revision": revision, "scenario": inputs['options'].get('scenario', ''), "results": results}


def reconcile(inputs: dict, embedder, revision: str) -> dict:
    directory = Path(inputs["project_directory"])
    samples: dict[str, list] = {}
    media_ids: dict[str, set] = {}
    sources = {m["id"]: m for m in inputs["media"]}
    for entry in inputs["clusters"]:
        source = sources[entry["media_id"]]
        if _hash_file(Path(source["source"])) != source["fingerprint"]:
            raise ValueError("A source changed; relink before comparing project speakers")
        # Use a clean representative, never combine overlapping voices.
        clean = next((t for t in entry["turns"] if not t["overlap"] and t["end"] - t["start"] >= 1.), None)
        if clean:
            region = {"start": clean["start"], "end": min(clean["end"], clean["start"] + 10.),
                      "fingerprint": source["fingerprint"]}
            samples.setdefault(entry["speaker_id"], []).append(reference_embedding(region, source, directory, embedder, revision))
            media_ids.setdefault(entry["speaker_id"], set()).add(source["id"])
    for region in inputs["references"]:
        if region["state"] == "ready":
            source = sources[region["media_id"]]
            if _hash_file(Path(source["source"])) != source["fingerprint"]:
                raise ValueError("Reference source changed; relink it before comparing")
            samples.setdefault(region["speaker_id"], []).append(reference_embedding(region, source, directory, embedder, revision))
            media_ids.setdefault(region["speaker_id"], set()).add(source["id"])
    vectors = {key: _unit(np.mean(values, axis=0)) for key, values in samples.items()}
    keys = list(vectors)
    proposals = []
    for index, left in enumerate(keys):
        for right in keys[index + 1:]:
            similarity = float(np.dot(vectors[left], vectors[right]))
            if similarity >= inputs["options"]["threshold"]:
                proposals.append({"left": left, "right": right, "similarity": similarity,
                                  "media_ids": sorted(media_ids[left] | media_ids[right])})
    for proposal in proposals:
        proposal["ambiguous"] = any(p is not proposal and
                                    {p["left"], p["right"]} & {proposal["left"], proposal["right"]} for p in proposals)
    return {"kind": "reconcile", "model_revision": revision, "proposals": proposals}


def run_editor_task(inputs: dict, progress) -> dict:
    action = inputs["action"]
    directory = Path(inputs["project_directory"])
    if action == "import":
        assets = []
        for path in inputs["paths"]:
            progress(f"Probing and caching waveform: {Path(path).name}")
            asset = probe_media(path)
            cache_waveform(asset["source"], directory, asset["fingerprint"])
            if _hash_file(Path(path)) != asset["fingerprint"]:
                raise ValueError("Media changed during import. Retry with a stable source file")
            assets.append(asset)
        return {"kind": "import", "assets": assets}
    if action == "validate":
        assets = []
        for source in inputs["media"]:
            progress(f"Checking source: {Path(source['source']).name}")
            try:
                metadata = probe_media(source["source"])
                if metadata["fingerprint"] != source["fingerprint"]:
                    assets.append({"id": source["id"], "status": "changed", "error": "Source content changed; relink it"})
                else:
                    cache_waveform(source["source"], directory, source["fingerprint"])
                    assets.append({**metadata, "id": source["id"], "status": "valid"})
            except (OSError, ValueError) as exc:
                assets.append({"id": source["id"], "status": "missing" if not Path(source["source"]).is_file() else "changed",
                               "error": str(exc)})
        return {"kind": "validate", "assets": assets}
    target = Path(inputs["target_path"])
    if _hash_file(target) != inputs["fingerprint"]:
        raise ValueError("Source content changed. Relink it before analysis")
    if action == 'cached':
        for source in inputs.get('related_sources', []):
            if _hash_file(Path(source['source'])) != source['fingerprint']:
                raise ValueError(f"A related source changed: {source['source']}. Relink before reusing this result")
        progress('Verified source fingerprint; reusing immutable cached inference')
        return json.loads(Path(inputs['result_path']).read_text(encoding='utf-8'))
    options = inputs["options"]
    if action == "stt":
        from .stt import STTOptions, transcribe
        payload = transcribe(target, STTOptions(**{k: v for k, v in options.items() if k != "model_revision"}),
                             progress=progress, total_seconds=inputs.get("source_duration"))
    elif action == "diarization":
        from .diarization import diarize
        payload = diarize(target, options["model_directory"], work_directory=Path(inputs.get('work_directory', directory / 'cache')))
    elif action == "summary":
        from .transcript import TranscriptDocument
        from .summarization import summarize
        document = json.loads(Path(inputs["document_path"]).read_text(encoding="utf-8"))
        for source in inputs.get('source_fingerprints', []):
            if _hash_file(Path(source['source'])) != source['fingerprint']:
                raise ValueError('A project source changed; relink it before generating a summary')
        payload = summarize(TranscriptDocument.restore(document), model=options["model"])
        payload["kind"] = "summary"
        payload['scope'] = options.get('scope', 'source')
        for source in inputs.get('source_fingerprints', []):
            if _hash_file(Path(source['source'])) != source['fingerprint']:
                raise ValueError('A project source changed during summary generation; refusing stale output')
    else:
        embedder, revision = _embedder(options["profile"])
        if action == "reference":
            region = inputs["region"]
            if inputs.get('diarization_path'):
                from .domain.speakers import has_overlapping_voices
                turns = json.loads(Path(inputs['diarization_path']).read_text(encoding='utf-8'))['turns']
                if has_overlapping_voices(turns, region['start'], region['end']):
                    raise ValueError('Reference contains overlapping voices. Choose a clean interval')
            vector = reference_embedding(region, inputs["source"], directory, embedder, revision)
            payload = {"kind": "reference", "model_revision": revision, "embedding": vector.tolist()}
        elif action == "locator":
            payload = match_references(inputs, embedder, revision, progress)
        elif action == "reconcile":
            payload = reconcile(inputs, embedder, revision)
        else:
            raise ValueError(f"Unknown project task: {action}")
    if _hash_file(target) != inputs["fingerprint"]:
        raise ValueError("Source changed during inference; refusing stale output")
    return payload
