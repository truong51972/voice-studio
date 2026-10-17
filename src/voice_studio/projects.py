"""Versioned local multi-file STT projects with guarded cache and atomic saves."""
from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .transcript import TranscriptDocument, export_text

VERSION = 1

def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

def _cache_key(fingerprint: str, settings: dict) -> str:
    canonical = json.dumps(settings, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256((fingerprint + "\0" + canonical).encode()).hexdigest()

def _atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    try:
        with temp.open("w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)

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

class ProjectStore:
    """No database, no accounts. Results stay within a user-selected directory."""

    def __init__(self, directory: Path, *, name: str = "Voice Studio project"):
        self.directory = Path(directory)
        self.manifest = self.directory / "project.json"
        self.name = name
        self.items: list[ProjectItem] = []
        if self.manifest.is_file():
            payload = json.loads(self.manifest.read_text(encoding="utf-8"))
            if payload.get("version") != VERSION:
                raise ValueError("Unsupported project manifest version")
            self.name = payload.get("name") or name
            self.items = [ProjectItem(**entry) for entry in payload["items"]]
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
        _atomic_json(self.manifest, {
            "version": VERSION, "name": self.name,
            "items": [asdict(item) for item in self.items],
        })

    def add(self, paths: list[str | Path]) -> None:
        known = {Path(item.source).resolve() for item in self.items}
        for source in paths:
            path = Path(source).resolve()
            if path in known:
                continue
            if not path.is_file():
                raise FileNotFoundError(path)
            self.items.append(ProjectItem(
                id=uuid.uuid4().hex, source=str(path),
                fingerprint=_hash_file(path), bytes=path.stat().st_size,
            ))
            known.add(path)
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
        _atomic_json(self._result_path(item), result)
        item.status = "completed"
        item.error = None
        item.duration = result.get("duration")
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
        _atomic_json(self._review_path(item), document.serialize())

    def combined_export(self, kind: str = "md") -> str:
        if kind not in ("md", "txt"):
            raise ValueError("Combined export is Markdown or TXT")
        sections = ["# Combined transcript\n"] if kind == "md" else []
        for index, item in enumerate(self.items, start=1):
            if item.status != "completed":
                continue
            document = self.review(item.id)
            title = f"File {index}: {Path(item.source).name}"
            sections.extend([
                f"\n## {title}\n" if kind == "md" else f"\n==== {title} ====\n",
                export_text(document, kind),
            ])
        return "\n".join(sections)
