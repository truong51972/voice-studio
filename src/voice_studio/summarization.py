"""Explicit local-only seminar summaries with validated source-segment citations.

All generated prose is an AI draft, never substituted for the raw transcript.
"""
from __future__ import annotations

import hashlib
import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .transcript import TranscriptDocument

SECTIONS = ("Executive summary", "Topics", "Speaker points", "Action items")

def _request_ollama(prompt: str, model: str) -> dict:
    """Only localhost Ollama is supported: no cloud endpoint and no implicit upload."""
    payload = json.dumps({
        "model": model, "prompt": prompt, "format": "json", "stream": False,
    }).encode("utf-8")
    request = urllib.request.Request(
        "http://127.0.0.1:11434/api/generate", data=payload,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            envelope = json.load(response)
    except Exception as exc:
        raise RuntimeError(
            "Cannot reach local Ollama at 127.0.0.1:11434; start Ollama and pull the selected model."
        ) from exc
    try:
        return json.loads(envelope["response"])
    except (KeyError, ValueError, TypeError) as exc:
        raise ValueError("Local model did not return the expected structured JSON") from exc

def _chunks(entries, *, max_chars: int = 7000):
    chunk, used = [], 0
    for segment in entries:
        line = f"[{segment.id} | {segment.start:.1f}-{segment.end:.1f}s | {segment.speaker_id or 'unknown'}] {segment.text}"
        if chunk and used + len(line) > max_chars:
            yield chunk
            chunk, used = [], 0
        chunk.append(segment)
        used += len(line) + 1
    if chunk:
        yield chunk

def summarize(
    document: TranscriptDocument, *, model: str,
    requester: Callable[[str, str], dict] | None = None,
) -> dict:
    if not model.strip():
        raise ValueError("Choose a local Ollama model")
    requester = requester or _request_ollama
    valid = {entry.id: entry for entry in document.edited}
    items = []
    for chunk in _chunks(document.edited):
        source = "\n".join(
            f"[{s.id} | {s.start:.1f}-{s.end:.1f}s | {s.speaker_id or 'unknown'}] {s.text}"
            for s in chunk
        )
        prompt = (
            "Summarize this meeting transcript, ONLY citing provided source segment IDs. "
            "Return JSON of form {\"items\":[{\"section\":\"Topics\","
            "\"text\":\"...\",\"source_ids\":[\"s1\"]}]}. Allowed sections: "
            + ", ".join(SECTIONS)
            + ". Do not invent facts, quotes, speakers, agreements or action ownership. "
              "Anything inferred must be phrased as a tentative AI interpretation. "
              "Never return items with no source IDs.\n\n"
            + source
        )
        response = requester(prompt, model)
        for proposed in response.get("items", []):
            if not isinstance(proposed, dict) or proposed.get("section") not in SECTIONS:
                continue
            cited = proposed.get("source_ids", [])
            if not isinstance(cited, list) or not cited:
                continue
            allowed = {s.id for s in chunk}
            if any(segment_id not in allowed for segment_id in cited):
                continue
            text = str(proposed.get("text", "")).strip()
            if not text:
                continue
            ranges = [[valid[sid].start, valid[sid].end] for sid in cited]
            items.append({
                "section": proposed["section"], "text": text,
                "source_ids": cited, "source_time_ranges": ranges,
                "label": "AI-generated draft — verify against source",
            })
    # Provenance snapshot, not AI-transformed transcript.
    fingerprint = hashlib.sha256(
        json.dumps(document.serialize(), sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    return {
        "kind": "local_summary", "version": 1,
        "source": document.raw_metadata.get("source"),
        "transcript_revision": document.revision,
        "transcript_sha256": fingerprint,
        "model": model, "provider": "Ollama (localhost only)",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "items": items,
    }

def summary_markdown(summary: dict) -> str:
    lines = [
        "# Meeting summary — AI draft (review required)", "",
        f"Source: \`{Path(summary.get('source') or 'unknown').name}\`",
        f"Local model: \`{summary.get('model', 'unknown')}\`",
        f"Transcript revision: {summary.get('transcript_revision', '?')}",
        "",
        "> AI-generated interpretations are not verbatim speech. Verify each item "
        "against its cited source time range before relying on it.",
    ]
    for section in SECTIONS:
        lines.extend(["", f"## {section}", ""])
        points = [item for item in summary.get("items", []) if item["section"] == section]
        if not points:
            lines.append("_No source-grounded draft items._")
        for item in points:
            times = "; ".join(
                f"{start:.1f}–{end:.1f}s" for start, end in item["source_time_ranges"]
            )
            lines.append(f"- **AI draft:** {item['text']} *(review audio at {times})*")
    return "\n".join(lines) + "\n"
