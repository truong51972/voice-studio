"""Editable transcript view; immutable model hypotheses and revisioned overrides.

No Qt imports: persistence in #8 can serialize the entire document.
"""
from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

@dataclass(frozen=True, slots=True)
class TranscriptEntry:
    id: str
    start: float
    end: float
    text: str
    speaker_id: str | None = None
    language: str | None = None
    words: tuple = ()
    speaker_source: str | None = None
    speaker_review_required: bool = False
    speaker_analysis_id: str | None = None

    @classmethod
    def from_dict(cls, row: dict):
        return cls(
            id=str(row["id"]), start=float(row["start"]), end=float(row["end"]),
            text=str(row["text"]), speaker_id=row.get("speaker_id"),
            language=row.get("language"), words=tuple(copy.deepcopy(row.get("words", []))),
            speaker_source=row.get("speaker_source"),
            speaker_review_required=bool(row.get("speaker_review_required", False)),
            speaker_analysis_id=row.get("speaker_analysis_id"),
        )

    def as_dict(self) -> dict:
        return {
            "id": self.id, "start": self.start, "end": self.end,
            "text": self.text, "speaker_id": self.speaker_id,
            "language": self.language, "words": copy.deepcopy(list(self.words)),
            "speaker_source": self.speaker_source,
            "speaker_review_required": self.speaker_review_required,
            "speaker_analysis_id": self.speaker_analysis_id,
        }

class TranscriptDocument:
    def __init__(self, raw: dict):
        if raw.get("kind") != "stt":
            raise ValueError("Expected raw STT inference result")
        self.raw_metadata = {k: copy.deepcopy(v) for k, v in raw.items() if k != "segments"}
        self.raw = tuple(TranscriptEntry.from_dict(row) for row in raw["segments"])
        self.edited = list(self.raw)
        self.revision = 0
        self.history: list[dict] = []

    def _index(self, identifier: str) -> int:
        for i, entry in enumerate(self.edited):
            if entry.id == identifier:
                return i
        raise KeyError(f"Transcript segment not found: {identifier}")

    def replace(self, identifier: str, *, text: str | None = None,
                speaker_id: str | None = None, rename_speaker: bool = False,
                speaker_source: str | None = "human", speaker_review_required: bool = False,
                speaker_analysis_id: str | None = None) -> None:
        i = self._index(identifier)
        old = self.edited[i]
        from dataclasses import replace as dc_replace
        self.edited[i] = dc_replace(
            old, text=old.text if text is None else text,
            speaker_id=(speaker_id if rename_speaker else old.speaker_id),
            speaker_source=speaker_source if rename_speaker else old.speaker_source,
            speaker_review_required=speaker_review_required if rename_speaker else old.speaker_review_required,
            speaker_analysis_id=speaker_analysis_id if rename_speaker else old.speaker_analysis_id,
            # Original word timestamps are no longer valid after an edit.
            words=() if text is not None and text != old.text else old.words,
        )
        self._record("replace", [identifier])

    def split(self, identifier: str, at: float) -> tuple[str, str]:
        i = self._index(identifier)
        old = self.edited[i]
        if not old.start < at < old.end:
            raise ValueError("Split position must lie strictly inside the segment")
        from dataclasses import replace as dc_replace
        a, b = identifier + "." + uuid4().hex[:8], identifier + "." + uuid4().hex[:8]
        # Do not invent missing words. Human must edit the split text.
        self.edited[i:i+1] = [
            dc_replace(old, id=a, end=at, text=old.text, words=()),
            dc_replace(old, id=b, start=at, text="", words=()),
        ]
        self._record("split", [identifier, a, b])
        return a, b

    def merge(self, first_id: str, second_id: str) -> str:
        a = self._index(first_id)
        b = self._index(second_id)
        if b != a + 1:
            raise ValueError("Only adjacent transcript segments can be merged")
        x, y = self.edited[a], self.edited[b]
        if y.start < x.start:
            raise ValueError("Transcript must be in media order")
        merged_id = first_id + "." + uuid4().hex[:8]
        merged = TranscriptEntry(
            id=merged_id, start=x.start, end=max(x.end, y.end),
            text=" ".join(z for z in (x.text.strip(), y.text.strip()) if z),
            speaker_id=x.speaker_id if x.speaker_id == y.speaker_id else None,
            language=x.language if x.language == y.language else None,
            speaker_source=("human" if "human" in (x.speaker_source, y.speaker_source)
                            else x.speaker_source if x.speaker_source == y.speaker_source else None),
            speaker_review_required=(x.speaker_review_required or y.speaker_review_required
                                     or x.speaker_id != y.speaker_id),
            speaker_analysis_id=x.speaker_analysis_id if x.speaker_analysis_id == y.speaker_analysis_id else None,
        )
        self.edited[a:b+1] = [merged]
        self._record("merge", [first_id, second_id, merged_id])
        return merged_id

    def reset(self) -> None:
        self.edited = list(self.raw)
        self._record("reset", [])

    def _record(self, operation: str, ids: list[str]) -> None:
        self.revision += 1
        self.history.append({"revision": self.revision, "operation": operation, "ids": ids})

    def find(self, phrase: str) -> list[int]:
        query = phrase.casefold().strip()
        return [i for i, s in enumerate(self.edited) if query in s.text.casefold()]

    def serialize(self) -> dict:
        return {
            "schema": 1, "raw": {**copy.deepcopy(self.raw_metadata), "segments": [s.as_dict() for s in self.raw]},
            "edited": [s.as_dict() for s in self.edited],
            "revision": self.revision, "history": copy.deepcopy(self.history),
        }

    def apply_diarization(self, turns: list[dict], *, analysis_id: str | None = None) -> None:
        from .diarization import attribute_segments
        proposed = attribute_segments([entry.as_dict() for entry in self.edited], turns, analysis_id=analysis_id)
        for old, row in zip(list(self.edited), proposed):
            new = TranscriptEntry.from_dict(row)
            if old != new:
                self.replace(old.id, speaker_id=new.speaker_id, rename_speaker=True,
                             speaker_source=new.speaker_source, speaker_analysis_id=new.speaker_analysis_id,
                             speaker_review_required=new.speaker_review_required)

    def selected_export(self, start: float, end: float) -> dict:
        """A reviewed selection, never a full raw/review archive.

        Segment text cannot be timed within a boundary segment without word
        timings. Omit that text rather than disclose speech outside the range.
        """
        if end <= start:
            raise ValueError("Choose a valid source selection before exporting")
        entries = []
        for entry in self.edited:
            if entry.end <= start or entry.start >= end:
                continue
            row = entry.as_dict()
            row.update(start=max(start, entry.start), end=min(end, entry.end))
            words = [dict(start=w['start'], end=w['end'], text=w['text']) for w in entry.words
                     if row['start'] <= w['start'] < w['end'] <= row['end']]
            row['words'] = words
            if entry.start < start or entry.end > end:
                row['text'] = ''.join(w['text'] for w in words).strip()
                row['text_requires_review'] = True
            entries.append(row)
        # Inference metadata can contain whole-source text/word arrays as well.
        metadata = {key: copy.deepcopy(self.raw_metadata[key]) for key in
                    ('source', 'current_source', 'media_id', 'content_fingerprint', 'model_id')
                    if key in self.raw_metadata}
        return {**metadata, 'scope': 'source_selection', 'timebase': 'source seconds',
                'source_in': start, 'source_out': end, 'review_revision': self.revision,
                'selected_segments': entries}

    @classmethod
    def restore(cls, payload: dict) -> "TranscriptDocument":
        if payload.get("schema") != 1:
            raise ValueError("Unsupported transcript document version")
        document = cls(payload["raw"])
        document.edited = [TranscriptEntry.from_dict(s) for s in payload["edited"]]
        document.revision = int(payload["revision"])
        document.history = copy.deepcopy(payload.get("history", []))
        return document

def _timestamp(seconds: float) -> str:
    milliseconds = round(max(0, seconds) * 1000)
    hours, rem = divmod(milliseconds, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    sec, ms = divmod(rem, 1000)
    return f"{hours:02}:{minutes:02}:{sec:02},{ms:03}"

def export_text(document: TranscriptDocument, kind: str, *, source_range: tuple[float, float] | None = None) -> str:
    selection = document.selected_export(*source_range) if source_range is not None else None
    entries = sorted((TranscriptEntry.from_dict(row) for row in selection['selected_segments'])
                     if selection is not None else document.edited, key=lambda s: (s.start, s.end))
    if kind == "json":
        return json.dumps(selection if selection is not None else document.serialize(), ensure_ascii=False, indent=2)
    if kind == "txt":
        source = document.raw_metadata.get('current_source', document.raw_metadata.get('source', 'unknown'))
        return f'Source: {Path(source).name} (source-relative timestamps)\n' + "\n".join(
            (f"[{_timestamp(s.start).replace(',', '.')}]" +
             (f" [{s.speaker_id}]" if s.speaker_id else "") + f" {s.text.strip()}")
            for s in entries if s.text.strip()
        ) + "\n"
    if kind == "md":
        meta = document.raw_metadata
        lines = [
            "# Transcript", "",
            f"Source: `{Path(meta.get('current_source', meta.get('source', 'unknown'))).name}`",
            f"Model: `{meta.get('model_id', 'unknown')}`",
            f"Edited revision: {document.revision}", "",
        ]
        for s in entries:
            if not s.text.strip():
                continue
            speaker = f" · {s.speaker_id}" if s.speaker_id else ""
            lines.append(
                f"**{_timestamp(s.start).replace(',', '.')} – {_timestamp(s.end).replace(',', '.')}{speaker}**  "
                + s.text.strip().replace("\n", " ")
            )
        return "\n".join(lines) + "\n"
    if kind == "srt":
        blocks = []
        for s in entries:
            if not s.text.strip():
                continue
            if s.end <= s.start:
                continue
            label = f"{s.speaker_id}: " if s.speaker_id else ""
            blocks.append(
                f"{len(blocks)+1}\n{_timestamp(s.start)} --> {_timestamp(s.end)}\n"
                + label + s.text.strip() + "\n"
            )
        return "\n".join(blocks) + ("\n" if blocks else "")
    raise ValueError(f"Unsupported transcript export format: {kind}")
