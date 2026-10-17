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
from .transcript import TranscriptDocument, export_text
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

    def __init__(self, directory: Path, *, name: str = "Voice Studio project"):
        self.directory = Path(directory).resolve()
        self.manifest = self.directory / "project.json"
        self.name = name
        self.id = uuid.uuid4().hex
        self.settings: dict = {}
        self.items: list[ProjectItem] = []
        self.clips: list[TimelineClip] = []
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
            self.clips = [replace(clip, source_in=0., source_out=None)
                          if clip.media_id == item.id else clip for clip in self.clips]
        elif item.status in ("missing", "changed"):
            item.status = "completed" if self._result_path(item).is_file() else "pending"
            item.error = None
        self.save()

    def get(self, identifier: str) -> ProjectItem:
        return next(i for i in self.items if i.id == identifier)

    def _result_path(self, item: ProjectItem) -> Path:
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
            return TranscriptDocument.restore(json.loads(review.read_text(encoding="utf-8")))
        source = self._result_path(item)
        if not source.is_file():
            raise FileNotFoundError(source)
        return TranscriptDocument(json.loads(source.read_text(encoding="utf-8")))

    def save_review(self, identifier: str, document: TranscriptDocument) -> None:
        item = self.get(identifier)
        if item.status != "completed":
            raise ValueError("Cannot save review without completed STT")
        _atomic_write(self._review_path(item), document.serialize())

    def combined_export(self, kind: str = "md") -> str:
        if kind not in ("md", "txt"):
            raise ValueError("Combined export is Markdown or TXT")
        sections = ["# Combined transcript\n"] if kind == "md" else []
        for index, clip in enumerate(self.clips, start=1):
            item = self.get(clip.media_id)
            if item.status != "completed":
                continue
            document = self.review(item.id)
            end = clip.end(item.duration)
            document.edited = [replace(entry, start=max(entry.start, clip.source_in), end=min(entry.end, end))
                               for entry in document.edited
                               if entry.end > clip.source_in and entry.start < end]
            title = f"File {index}: {Path(item.source).name}"
            sections.extend([
                f"\n## {title}\n" if kind == "md" else f"\n==== {title} ====\n",
                f"Source interval: {clip.source_in:.3f}–{end:.3f}s (source-relative timestamps)\n",
                export_text(document, kind),
            ])
        return "\n".join(sections)
