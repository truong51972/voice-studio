"""Versioned local multi-file STT projects with guarded cache and atomic saves."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import uuid
from dataclasses import asdict, dataclass, replace
from math import isfinite
from pathlib import Path

from .domain.timeline import TimelineClip, TimelineMap
from .domain.speakers import AnalysisRecord, ProjectSpeaker, ReferenceRegion, has_overlapping_voices
from .transcript import TranscriptDocument, TranscriptEntry, export_text
from .subtitle_formats import parse_subtitles, serialize_subtitles
from .workspace import projects_directory

VERSION = 2

def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

def _cache_key(fingerprint: str, settings: dict) -> str:
    canonical = json.dumps(settings, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256((fingerprint + "\0" + canonical).encode()).hexdigest()

def _atomic_write(path: Path, value: dict | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        binary = isinstance(value, bytes)
        with tempfile.NamedTemporaryFile(mode="wb" if binary else "w", encoding=None if binary else "utf-8", dir=path.parent,
                                         prefix=path.name + ".", suffix=".tmp", delete=False) as handle:
            temp = Path(handle.name)
            if binary:
                handle.write(value)
            else:
                json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


def _identifier(value: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise ValueError("Invalid project/media/clip ID")

@dataclass
class ProjectItem:
    id: str
    source: str
    fingerprint: str
    bytes: int
    settings_key: str = ""
    status: str = "pending"
    error: str | None = None
    duration: float | None = None
    kind: str | None = None
    mtime_ns: int = 0

    def __post_init__(self):
        _identifier(self.id)
        if self.settings_key:
            _identifier(self.settings_key)
        if self.duration is not None and (not isfinite(self.duration) or self.duration < 0):
            raise ValueError("Media duration must be finite and nonnegative")
        if self.kind not in (None, "audio", "video"):
            raise ValueError("Unsupported media kind")

class ProjectStore:
    """Versioned metadata and source-local results, independent of Qt.

    The desktop creates projects with create_portable(). Explicit directories
    remain supported for opening/migrating legacy projects and deterministic tests.
    """

    def __init__(self, directory: Path, *, name: str = "Voice Studio project", check_sources: bool = True):
        self.directory = Path(directory).resolve()
        self.manifest = self.directory / "project.json"
        self.name = name
        self.id = uuid.uuid4().hex
        self.settings: dict = {}
        self.items: list[ProjectItem] = []
        self.clips: list[TimelineClip] = []
        self.speakers: list[ProjectSpeaker] = []
        self.references: list[ReferenceRegion] = []
        self.analyses: list[AnalysisRecord] = []
        self.cluster_mappings: dict[str, dict[str, str]] = {}
        self.proposals: list[dict] = []
        if self.manifest.is_file():
            original = self.manifest.read_bytes()
            payload = json.loads(original)
            if not isinstance(payload, dict):
                raise ValueError("Project manifest must be a JSON object")
            version = payload.get("version")
            if version not in (1, VERSION):
                raise ValueError(f"Unsupported project manifest version: {version}. Use a compatible Voice Studio release.")
            self.name = payload.get("name") or name
            self.items = [ProjectItem(**entry) for entry in payload["items" if version == 1 else "media"]]
            if version == 1:
                self.clips = [TimelineClip(uuid.uuid4().hex, item.id) for item in self.items]
            else:
                self.id = payload["id"]
                self.settings = payload["settings"]
                self.clips = [TimelineClip(**entry) for entry in payload["clips"]]
                self.speakers = [ProjectSpeaker(**entry) for entry in payload.get("speakers", [])]
                self.references = [ReferenceRegion(**entry) for entry in payload.get("references", [])]
                self.analyses = [AnalysisRecord(**entry) for entry in payload.get("analyses", [])]
                self.cluster_mappings = payload.get("cluster_mappings", {})
                self.proposals = payload.get("proposals", [])
            self._validate()
            if version == 1:
                backup = self.manifest.with_name("project.v1.backup.json")
                # A retry after an interrupted migration must never overwrite its backup.
                if not backup.exists():
                    _atomic_write(backup, original)
            for item in self.items:
                if item.status == "running":
                    item.status = "interrupted"
                    item.error = "Previous process was interrupted; retry this item."
            for record in self.analyses:
                if record.state in ("running", "queued"):
                    record.state = "interrupted"
                    record.error = "Previous process was interrupted; retry this analysis."
            for operation in self.settings.get('operations', []):
                if operation['state'] in ('queued', 'running'):
                    operation['state'] = 'interrupted'
                    operation['error'] = 'Previous process was interrupted; retry the operation'
            if check_sources:
                self._check_changed_sources()
            self.save()
        else:
            self.directory.mkdir(parents=True, exist_ok=True)
            self.save()

    def save(self) -> None:
        self._validate()
        _atomic_write(self.manifest, {
            "version": VERSION, "id": self.id, "name": self.name,
            "settings": self.settings,
            "media": [asdict(item) for item in self.items],
            "clips": [asdict(clip) for clip in self.clips],
            "speakers": [asdict(s) for s in self.speakers],
            "references": [asdict(r) for r in self.references],
            "analyses": [asdict(r) for r in self.analyses],
            "cluster_mappings": self.cluster_mappings, "proposals": self.proposals,
        })

    @classmethod
    def create_portable(cls, name: str = "Voice Studio project") -> ProjectStore:
        directory = projects_directory() / uuid.uuid4().hex
        try:
            return cls(directory, name=name)
        except Exception:
            # Only an empty, newly allocated folder may be removed on failed creation.
            if directory.is_dir() and not any(directory.iterdir()):
                directory.rmdir()
            raise

    def _validate(self) -> None:
        _identifier(self.id)
        if not isinstance(self.settings, dict):
            raise ValueError("Project settings must be a JSON object")
        for group in (self.speakers, self.references, self.analyses):
            if len({entry.id for entry in group}) != len(group):
                raise ValueError("Project record IDs must be unique")
            for entry in group:
                _identifier(entry.id)
        media_ids = {item.id for item in self.items}
        speaker_ids = {speaker.id for speaker in self.speakers}
        for speaker in self.speakers:
            if speaker.merged_into is not None and speaker.merged_into not in speaker_ids:
                raise ValueError('Speaker merge target is missing')
            self.speaker(speaker.id)
        for region in self.references:
            if region.media_id not in media_ids or region.speaker_id not in speaker_ids:
                raise ValueError("Reference links to unknown media/speaker")
            if region.fingerprint == self.get(region.media_id).fingerprint:
                region.validate(self.get(region.media_id).duration)
        for record in self.analyses:
            if record.media_id not in media_ids:
                raise ValueError("Analysis links to unknown media")
        for mapping in self.cluster_mappings.values():
            if any(speaker_id not in speaker_ids for speaker_id in mapping.values()):
                raise ValueError("Cluster mapping links to unknown speaker")
        media = {item.id: item for item in self.items}
        if len(media) != len(self.items) or len({c.id for c in self.clips}) != len(self.clips):
            raise ValueError("Project media and clip IDs must be unique")
        for clip in self.clips:
            _identifier(clip.id)
            if clip.media_id not in media:
                raise ValueError("Timeline clip references unknown media")
            duration = media[clip.media_id].duration
            if duration is not None and duration > 0:
                clip.end(duration)

    def timeline(self) -> TimelineMap:
        return TimelineMap(self.clips, {item.id: item.duration for item in self.items})

    def reorder_clips(self, identifiers: list[str]) -> None:
        if len(identifiers) != len(self.clips) or set(identifiers) != {c.id for c in self.clips}:
            raise ValueError("Reorder must contain every clip exactly once")
        clips = {clip.id: clip for clip in self.clips}
        self.clips = [clips[key] for key in identifiers]
        self.save()

    def trim_clip(self, identifier: str, source_in: float, source_out: float) -> None:
        index = next(i for i, c in enumerate(self.clips) if c.id == identifier)
        clip = replace(self.clips[index], source_in=source_in, source_out=source_out)
        clip.end(self.get(clip.media_id).duration)
        self.clips[index] = clip
        self.save()

    def import_assets(self, assets: list[dict]) -> None:
        """Commit already probed/hashed worker metadata as one import operation."""
        additions = []
        for metadata in assets:
            path = str(Path(metadata["source"]).resolve())
            existing = next((m for m in self.items if m.source == path), None)
            if existing:
                if existing.fingerprint != metadata["fingerprint"]:
                    raise ValueError("Source changed; relink it explicitly before reimporting")
                existing.duration = metadata["duration"]
                existing.kind = metadata["kind"]
                existing.mtime_ns = metadata["mtime_ns"]
                if existing.status in ('missing', 'changed'):
                    existing.status = 'completed' if self._result_path(existing).is_file() else 'pending'
                    existing.error = None
                continue
            moved = next((m for m in self.items if m.fingerprint == metadata["fingerprint"]
                          and not Path(m.source).is_file()), None)
            if moved:
                moved.source = path
                for key in ("mtime_ns", "duration", "kind", "bytes"):
                    setattr(moved, key, metadata[key])
                moved.status = "completed" if self._result_path(moved).is_file() else "pending"
                moved.error = None
                continue
            item = ProjectItem(id=uuid.uuid4().hex, **{k: v for k, v in metadata.items()
                               if k in ("source", "fingerprint", "bytes", "duration", "kind", "mtime_ns")})
            if any(a.source == item.source for a in additions):
                continue
            additions.append(item)
        self.items.extend(additions)
        self.clips.extend(TimelineClip(uuid.uuid4().hex, item.id) for item in additions)
        self.save()

    def relink_asset(self, media_id: str, metadata: dict) -> None:
        item = self.get(media_id)
        changed = item.fingerprint != metadata["fingerprint"]
        if changed:
            item.settings_key = ""
            for region in self.references:
                if region.media_id == media_id:
                    region.state, region.error = "invalid", "Source changed; choose a new reference"
            self.clips = [replace(c, source_in=0., source_out=None) if c.media_id == media_id else c for c in self.clips]
        for key in ("source", "fingerprint", "bytes", "duration", "kind", "mtime_ns"):
            setattr(item, key, metadata[key])
        item.status = "completed" if not changed and self._result_path(item).is_file() else "pending"
        item.error = None
        self.save()

    def analysis_path(self, record_id: str) -> Path:
        _identifier(record_id)
        return self.directory / "results" / f"{record_id}.json"

    def cached_analysis(self, media_id: str, task: str, settings: dict) -> AnalysisRecord | None:
        fingerprint = self.get(media_id).fingerprint
        return next((r for r in reversed(self.analyses) if r.media_id == media_id
                     and r.task == task and r.fingerprint == fingerprint and r.settings == settings
                     and r.state == "completed" and self.analysis_path(r.id).is_file()), None)

    def latest_analysis(self, media_id: str, task: str) -> AnalysisRecord | None:
        return next((r for r in reversed(self.analyses) if r.media_id == media_id and r.task == task
                     and r.fingerprint == self.get(media_id).fingerprint and r.state == "completed"
                     and self.analysis_path(r.id).is_file()), None)

    def result(self, record: AnalysisRecord) -> dict:
        return json.loads(self.analysis_path(record.id).read_text(encoding="utf-8"))

    def queue_analysis(self, media_id: str, task: str, settings: dict) -> AnalysisRecord:
        item = self.get(media_id)
        if item.status in ("missing", "changed"):
            raise ValueError(item.error)
        record = AnalysisRecord(uuid.uuid4().hex, media_id, task, item.fingerprint, settings)
        self.analyses.append(record)
        self.save()
        return record

    def finish_analysis(self, record: AnalysisRecord, payload: dict) -> None:
        if payload.get("kind") != record.task:
            raise ValueError("Worker output task does not match its project job")
        if record.fingerprint != self.get(record.media_id).fingerprint:
            raise ValueError("Media fingerprint changed; refusing stale inference")
        if record.state not in ("running", "queued"):
            raise ValueError("Analysis is not active")
        _atomic_write(self.analysis_path(record.id), payload)
        record.state = "completed"
        record.error = None
        item = self.get(record.media_id)
        if record.task == "stt":
            item.settings_key = record.id
            item.status = "completed"
        elif record.task == "diarization":
            mapping = {}
            for turn in payload["turns"] + payload.get("exclusive_turns", []):
                cluster = turn.get("cluster_id", turn["speaker_id"])
                if cluster not in mapping:
                    speaker = self.create_speaker(f"Speaker {len(self.speakers) + 1}", save=False)
                    mapping[cluster] = speaker.id
            self.cluster_mappings[record.id] = mapping
            for region in self.references:
                if region.media_id == record.media_id and has_overlapping_voices(payload['turns'], region.start, region.end):
                    region.state, region.error = 'invalid', 'Detected overlapping voices; select a clean reference interval'
        elif record.task == "reference":
            region = next(r for r in self.references if r.id == record.settings["region_id"])
            region.state = "ready"
            region.model_revision = payload["model_revision"]
            region.error = None
        for proposal in payload.get("proposals", []):
            candidate = {**proposal, "state": "pending", "analysis_id": record.id}
            if not any(p.get("left") == candidate.get("left") and p.get("right") == candidate.get("right")
                       and p.get("state") == "pending" for p in self.proposals):
                self.proposals.append(candidate)
        self.save()
        if record.task in ("stt", "diarization"):
            self.attribute_review(record.media_id)

    def attribute_review(self, media_id: str) -> None:
        item = self.get(media_id)
        diarization = self.latest_analysis(media_id, "diarization")
        if item.status != "completed" or diarization is None:
            return
        document = self.review(media_id)
        revision = document.revision
        document.apply_diarization(self.mapped_turns(diarization, exclusive=True), analysis_id=diarization.id)
        if document.revision != revision:
            self.save_review(media_id, document)

    def create_speaker(self, name: str, *, save: bool = True) -> ProjectSpeaker:
        if not name.strip():
            raise ValueError("Speaker name cannot be empty")
        colors = ("#36c5d8", "#a78bfa", "#f6b94a", "#f472b6", "#4ade80")
        speaker = ProjectSpeaker(uuid.uuid4().hex, name.strip(), colors[len(self.speakers) % len(colors)])
        self.speakers.append(speaker)
        if save:
            self.save()
        return speaker

    def rename_speaker(self, speaker_id: str, name: str) -> None:
        if not name.strip():
            raise ValueError("Speaker name cannot be empty")
        next(s for s in self.speakers if s.id == speaker_id).name = name.strip()
        self.save()

    def merge_speakers(self, keep: str, remove: str) -> None:
        if keep == remove or {keep, remove} - {s.id for s in self.speakers}:
            raise ValueError("Choose two different project speakers")
        if self.speaker(keep).id != keep or self.speaker(remove).id != remove:
            raise ValueError("Choose two active project speakers")
        for mapping in self.cluster_mappings.values():
            for cluster, speaker in mapping.items():
                if speaker == remove:
                    mapping[cluster] = keep
        for region in self.references:
            if region.speaker_id == remove:
                region.speaker_id = keep
        # Resolve historical review IDs through the alias on load: one atomic
        # manifest commit avoids partially rewriting a project's review files.
        next(s for s in self.speakers if s.id == remove).merged_into = keep
        for proposal in self.proposals:
            if proposal.get("state") == "pending" and remove in (proposal.get("left"), proposal.get("right")):
                proposal["state"] = "accepted" if keep in (proposal.get("left"), proposal.get("right")) else "obsolete"
        self.save()

    def speaker(self, speaker_id: str) -> ProjectSpeaker:
        seen = set()
        while speaker_id not in seen:
            seen.add(speaker_id)
            speaker = next(s for s in self.speakers if s.id == speaker_id)
            if speaker.merged_into is None:
                return speaker
            speaker_id = speaker.merged_into
        raise ValueError("Cyclic speaker mapping")

    def split_cluster(self, record_id: str, cluster_id: str, name: str) -> str:
        from .diarization import dominant_speaker
        mapping = self.cluster_mappings[record_id]
        if cluster_id not in mapping:
            raise ValueError("Unknown source cluster")
        old_speaker = mapping[cluster_id]
        speaker = self.create_speaker(name, save=False)
        mapping[cluster_id] = speaker.id
        record = next(r for r in self.analyses if r.id == record_id)
        turns = [t for t in self.result(record)["turns"] if t.get("cluster_id", t["speaker_id"]) == cluster_id]
        item = self.get(record.media_id)
        if item.status == "completed":
            document = self.review(item.id)
            mapped = self.mapped_turns(record)
            for entry in list(document.edited):
                # Legacy labels without provenance may be human corrections.
                if (entry.speaker_source == 'diarization' and entry.speaker_id == old_speaker
                        and any(t['start'] < entry.end and entry.start < t['end'] for t in turns)):
                    assigned = dominant_speaker(entry.start, entry.end, mapped)
                    document.replace(entry.id, speaker_id=assigned, rename_speaker=True,
                                     speaker_source='diarization', speaker_analysis_id=record.id,
                                     speaker_review_required=assigned is None)
            self.save_review(item.id, document)
        self.save()
        return speaker.id

    def mapped_turns(self, record: AnalysisRecord, *, exclusive: bool = False) -> list[dict]:
        payload = self.result(record)
        turns = payload.get("exclusive_turns", payload["turns"]) if exclusive else payload["turns"]
        mapping = self.cluster_mappings.get(record.id, {})
        return [{**turn, "speaker_id": mapping.get(turn.get("cluster_id", turn["speaker_id"]))}
                for turn in turns]

    def add_reference(self, speaker_id: str, media_id: str, start: float, end: float) -> ReferenceRegion:
        if speaker_id not in {s.id for s in self.speakers}:
            raise ValueError("Choose a project speaker")
        item = self.get(media_id)
        region = ReferenceRegion(uuid.uuid4().hex, speaker_id, media_id, start, end, item.fingerprint)
        self.validate_reference(region)
        self.references.append(region)
        self.save()
        return region

    def validate_reference(self, region: ReferenceRegion) -> None:
        item = self.get(region.media_id)
        if region.fingerprint != item.fingerprint:
            raise ValueError('Source changed; select a new reference')
        region.validate(item.duration)
        if region.end - region.start < 1.:
            raise ValueError("Select at least 1 second of clean speech; 3–10 seconds is useful guidance")
        diarization = self.latest_analysis(region.media_id, "diarization")
        if diarization:
            turns = self.result(diarization)["turns"]
            if has_overlapping_voices(turns, region.start, region.end):
                raise ValueError("Selection contains overlapping voices. Choose a clean single-speaker interval")

    def export_document(self, media_id: str) -> TranscriptDocument:
        document = self.review(media_id)
        item = self.get(media_id)
        document.raw_metadata.update(current_source=item.source, media_id=item.id, content_fingerprint=item.fingerprint)
        names = {s.id: self.speaker(s.id).name for s in self.speakers}
        document.edited = [replace(s, speaker_id=names.get(s.speaker_id, s.speaker_id)) for s in document.edited]
        return document

    def summary_document(self) -> TranscriptDocument:
        """Ordered review snapshot with explicit source anchors for every citation."""
        entries, anchors = [], {}
        revisions = {}
        for clip in self.clips:
            item = self.get(clip.media_id)
            document = self.export_document(item.id)
            revisions[item.id] = {'review_revision': document.revision, 'fingerprint': item.fingerprint}
            end = clip.end(item.duration)
            for segment in document.edited:
                start, stop = max(clip.source_in, segment.start), min(end, segment.end)
                if stop <= start:
                    continue
                identifier = clip.id + '-' + segment.id
                entries.append(replace(segment, id=identifier, start=start, end=stop,
                                       text=f'[{Path(item.source).name}] {segment.text}').as_dict())
                anchors[identifier] = {'media_id': item.id, 'source': item.source, 'start': start, 'end': stop}
        snapshot = TranscriptDocument({'kind': 'stt', 'source': self.name, 'segments': entries,
                                       'source_anchors': anchors, 'source_revisions': revisions,
                                       'derived_review_snapshot': True})
        snapshot.revision = sum(record['review_revision'] for record in revisions.values())
        return snapshot

    def add(self, paths: list[str | Path]) -> None:
        known = {Path(item.source).resolve() for item in self.items}
        additions = []
        for source in paths:
            path = Path(source).resolve()
            if path in known:
                continue
            if not path.is_file():
                raise FileNotFoundError(path)
            additions.append(ProjectItem(
                id=uuid.uuid4().hex, source=str(path),
                fingerprint=_hash_file(path), bytes=path.stat().st_size,
            ))
            known.add(path)
        self.items.extend(additions)
        self.clips.extend(TimelineClip(uuid.uuid4().hex, item.id) for item in additions)
        self.save()

    def _check_changed_sources(self) -> None:
        for item in self.items:
            path = Path(item.source)
            if not path.is_file():
                item.status = "missing"
                item.error = "Source media missing; relink it before processing."
                continue
            if _hash_file(path) != item.fingerprint:
                item.status = "changed"
                item.error = "Source content changed; reimport/relink to invalidate stale results."

    def relink(self, identifier: str, path: str | Path) -> None:
        item = self.get(identifier)
        if item.status == "running":
            raise ValueError("Finish/cancel the running job before relinking media")
        replacement = Path(path).resolve()
        if not replacement.is_file():
            raise FileNotFoundError(replacement)
        fingerprint = _hash_file(replacement)
        item.source = str(replacement)
        item.bytes = replacement.stat().st_size
        if fingerprint != item.fingerprint:
            item.fingerprint = fingerprint
            item.settings_key = ""
            item.status = "pending"
            item.error = "New fingerprint; previous results invalidated."
            item.duration = None
            item.kind = None
            for region in self.references:
                if region.media_id == item.id:
                    region.state = "invalid"
                    region.error = "Source content changed; select a new reference"
            self.clips = [replace(clip, source_in=0., source_out=None)
                          if clip.media_id == item.id else clip for clip in self.clips]
        elif item.status in ("missing", "changed"):
            item.status = "completed" if self._result_path(item).is_file() else "pending"
            item.error = None
        self.save()

    def get(self, identifier: str) -> ProjectItem:
        return next(i for i in self.items if i.id == identifier)

    def _result_path(self, item: ProjectItem) -> Path:
        if any(r.id == item.settings_key for r in self.analyses):
            return self.analysis_path(item.settings_key)
        return self.directory / "results" / f"{item.id}-{item.settings_key}.json"

    def _review_path(self, item: ProjectItem) -> Path:
        return self.directory / "reviews" / f"{item.id}-{item.settings_key}.json"

    def should_run(self, item: ProjectItem, options: dict) -> bool:
        if item.status in ("missing", "changed"):
            return False
        new_key = _cache_key(item.fingerprint, options)
        if item.settings_key != new_key:
            return True
        return item.status != "completed" or not self._result_path(item).is_file()

    def begin(self, identifier: str, options: dict) -> None:
        item = self.get(identifier)
        if item.status in ("missing", "changed"):
            raise ValueError(item.error)
        item.settings_key = _cache_key(item.fingerprint, options)
        item.status = "running"
        item.error = None
        self.save()

    def complete(self, identifier: str, result: dict) -> None:
        item = self.get(identifier)
        if item.status != "running":
            raise RuntimeError("Cannot complete a job not running")
        if _hash_file(Path(item.source)) != item.fingerprint:
            item.status = "changed"
            item.error = "Media changed during inference; refusing stale result."
            self.save()
            raise ValueError(item.error)
        if result.get("kind") != "stt":
            raise ValueError("Expected STT result")
        _atomic_write(self._result_path(item), result)
        item.status = "completed"
        item.error = None
        if item.duration is None:
            duration = result.get("duration")
            if duration is not None and isfinite(duration) and duration > 0:
                item.duration = duration
        self.save()

    def fail(self, identifier: str, error: str) -> None:
        item = self.get(identifier)
        item.status = "failed"
        item.error = error
        self.save()

    def review(self, identifier: str) -> TranscriptDocument:
        item = self.get(identifier)
        if item.status != "completed":
            raise ValueError("No completed transcript for this media")
        review = self._review_path(item)
        if review.is_file():
            document = TranscriptDocument.restore(json.loads(review.read_text(encoding="utf-8")))
        else:
            source = self._result_path(item)
            if not source.is_file():
                raise FileNotFoundError(source)
            document = TranscriptDocument(json.loads(source.read_text(encoding="utf-8")))
        # Reviewed cue timing/text is stored in a standard WebVTT track. Legacy
        # JSON-only projects are transparently read until their next save.
        track = self._review_path(item).with_suffix(".vtt")
        if track.is_file():
            document.load_subtitle_cues(parse_subtitles(track.read_text(encoding="utf-8"), "vtt"))
        known = {s.id for s in self.speakers}
        for entry in list(document.edited):
            if entry.speaker_id in known:
                canonical = self.speaker(entry.speaker_id).id
                if canonical != entry.speaker_id:
                    document.replace(entry.id, speaker_id=canonical, rename_speaker=True,
                                     speaker_source=entry.speaker_source,
                                     speaker_analysis_id=entry.speaker_analysis_id,
                                     speaker_review_required=entry.speaker_review_required)
        return document

    def save_review(self, identifier: str, document: TranscriptDocument, *, settings_key: str | None = None) -> None:
        item = self.get(identifier)
        if settings_key is not None:
            _identifier(settings_key)
            original = next((r for r in self.analyses if r.id == settings_key), None)
            if original and (original.media_id != identifier or original.task != 'stt'):
                raise ValueError('Review belongs to a different media/task')
            archived = self.analysis_path(settings_key)
            legacy = self.directory / 'results' / f'{item.id}-{settings_key}.json'
            if not archived.is_file() and not legacy.is_file():
                raise ValueError('Cannot save review without its original inference result')
            path = self.directory / 'reviews' / f'{item.id}-{settings_key}.json'
        elif item.status != "completed":
            raise ValueError("Cannot save review without completed STT")
        else:
            path = self._review_path(item)
        # WebVTT is the editable source-of-truth for reviewed cue timing and
        # text; the JSON companion retains inference lineage and correction
        # metadata, not an independent subtitle playback format.
        _atomic_write(path.with_suffix(".vtt"),
                      serialize_subtitles(document.subtitle_cues(), include_empty=True).encode("utf-8"))
        _atomic_write(path, document.serialize())

    def combined_export(self, kind: str = "md") -> str:
        if kind not in ("md", "txt", "srt", "vtt", "json"):
            raise ValueError("Choose WebVTT, Markdown, TXT, SRT or JSON")
        if kind in ("srt", "vtt", "json"):
            mapping = self.timeline()
            payload = {"project_id": self.id, "name": self.name, "scope": "selected_timeline",
                       "timebase": "timeline_start: project seconds; segment/word times: source seconds", "clips": []}
            combined = TranscriptDocument({"kind": "stt", "source": self.name, "segments": []})
            for clip in self.clips:
                item = self.get(clip.media_id)
                if item.status != "completed":
                    continue
                document = self.export_document(item.id)
                end = clip.end(item.duration)
                if kind == 'json':
                    payload["clips"].append({**document.selected_export(clip.source_in, end),
                        "clip_id": clip.id, "fingerprint": item.fingerprint,
                        "timeline_start": mapping.starts[clip.id]})
                    continue
                entries = [TranscriptEntry.from_dict(row) for row in document.selected_export(clip.source_in, end)['selected_segments']]
                combined.edited.extend(replace(s, id=clip.id + '-' + s.id,
                    start=mapping.source_to_project(clip.id, s.start), end=mapping.source_to_project(clip.id, s.end),
                    text=f'[{Path(item.source).name}] {s.text}') for s in entries if s.text.strip())
            return json.dumps(payload, ensure_ascii=False, indent=2) if kind == "json" else export_text(combined, kind)
        sections = ["# Combined transcript\n"] if kind == "md" else []
        for index, clip in enumerate(self.clips, start=1):
            item = self.get(clip.media_id)
            if item.status != "completed":
                continue
            document = self.export_document(item.id)
            end = clip.end(item.duration)
            title = f"File {index}: {Path(item.source).name}"
            sections.extend([
                f"\n## {title}\n" if kind == "md" else f"\n==== {title} ====\n",
                f"Source interval: {clip.source_in:.3f}–{end:.3f}s (source-relative timestamps)\n",
                export_text(document, kind, source_range=(clip.source_in, end)),
            ])
        return "\n".join(sections)
