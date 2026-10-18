"""Standards-based WebVTT / SubRip cue parser and serializer.

No Qt dependency. WebVTT (UTF-8) is the portable editable subtitle source;
inference metadata/revision history remain in separate project artifacts.
"""
from __future__ import annotations

from dataclasses import dataclass
from html import escape, unescape
from math import isfinite
import re


@dataclass(frozen=True, slots=True)
class SubtitleCue:
    id: str
    start: float
    end: float
    text: str


_VTT_TIMING = re.compile(
    r"^((?:\d{2,}:)?[0-5]\d:[0-5]\d\.\d{3})\s+-->\s+"
    r"((?:\d{2,}:)?[0-5]\d:[0-5]\d\.\d{3})(?:\s+.*)?$"
)
_SRT_TIMING = re.compile(
    r"^(\d{2,}:[0-5]\d:[0-5]\d,\d{3})\s+-->\s+"
    r"(\d{2,}:[0-5]\d:[0-5]\d,\d{3})$"
)


def _seconds(value: str) -> float:
    parts = value.replace(",", ".").split(":")
    if len(parts) == 2:
        minutes, seconds = parts
        hours = 0
    elif len(parts) == 3:
        hours, minutes, seconds = parts
    else:
        raise ValueError(f"Invalid subtitle timestamp: {value}")
    seconds_value = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    if not isfinite(seconds_value):
        raise ValueError("Invalid subtitle time")
    return seconds_value


def _stamp(seconds: float, *, srt: bool = False) -> str:
    if not isfinite(seconds) or seconds < 0:
        raise ValueError("Subtitle time must be non-negative and finite")
    milliseconds = round(seconds * 1000)
    hours, rest = divmod(milliseconds, 3600000)
    minutes, rest = divmod(rest, 60000)
    secs, ms = divmod(rest, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02}{',' if srt else '.'}{ms:03}"


def serialize_subtitles(cues, kind: str = "vtt", *, include_empty: bool = False) -> str:
    if kind not in ("vtt", "srt"):
        raise ValueError("Use WebVTT (.vtt) or SubRip (.srt)")
    ordered = sorted((c for c in cues if include_empty or c.text.strip()), key=lambda c: c.start)
    blocks = []
    for index, cue in enumerate(ordered, start=1):
        if not isfinite(cue.start) or not isfinite(cue.end) or cue.start < 0 or cue.end <= cue.start:
            raise ValueError(f"Invalid subtitle cue time: {cue.id}")
        timing = f"{_stamp(cue.start, srt=kind == 'srt')} --> {_stamp(cue.end, srt=kind == 'srt')}"
        # Payload is escaped as text, not interpreted as WebVTT markup.
        payload = escape(cue.text.strip(), quote=False) if kind == "vtt" else cue.text.strip()
        if kind == "vtt":
            identifier = cue.id if cue.id and "-->" not in cue.id and "\n" not in cue.id else str(index)
            blocks.append(f"{identifier}\n{timing}\n{payload}")
        else:
            blocks.append(f"{index}\n{timing}\n{payload}")
    prefix = "WEBVTT\n\n" if kind == "vtt" else ""
    return prefix + "\n\n".join(blocks) + ("\n" if blocks else "")


def parse_subtitles(content: str, kind: str | None = None) -> list[SubtitleCue]:
    """Parse UTF-8 WebVTT/SRT cues; retain stable WebVTT IDs and multiline text.

    Unsupported WebVTT NOTE/STYLE/REGION blocks are ignored. Timing settings
    are valid WebVTT metadata but not required for our plain-text editor.
    Malformed cue time ranges fail instead of silently creating false captions.
    """
    normalized = content.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    if kind is None:
        kind = "vtt" if normalized.startswith("WEBVTT") else "srt"
    if kind not in ("vtt", "srt"):
        raise ValueError("Unsupported subtitle file type")
    if kind == "vtt":
        head, sep, rest = normalized.partition("\n")
        if not head.startswith("WEBVTT") or (len(head) > 6 and head[6] not in (" ", "\t")):
            raise ValueError("WebVTT files must start with WEBVTT")
        normalized = rest
    matcher = _VTT_TIMING if kind == "vtt" else _SRT_TIMING
    cues = []
    seen = set()
    for block in re.split(r"\n[ \t]*\n+", normalized.strip()):
        lines = block.split("\n")
        if not lines or not lines[0].strip():
            continue
        if kind == "vtt" and lines[0].startswith(("NOTE", "STYLE", "REGION")):
            continue
        identifier = ""
        timing_line = 0
        if not matcher.fullmatch(lines[0].strip()):
            if "-->" in lines[0]:
                raise ValueError("Invalid subtitle timestamp syntax")
            identifier = lines[0].strip()
            timing_line = 1
        if timing_line >= len(lines):
            continue  # e.g. WebVTT header metadata
        timing = matcher.fullmatch(lines[timing_line].strip())
        if timing is None:
            if "-->" in lines[timing_line]:
                raise ValueError("Invalid subtitle timestamp syntax")
            continue
        start, end = _seconds(timing[1]), _seconds(timing[2])
        if end <= start:
            raise ValueError("Subtitle cue end must follow its start")
        key = identifier if kind == "vtt" and identifier else f"cue-{len(cues) + 1:06d}"
        if key in seen:
            raise ValueError("Duplicate subtitle cue identifier")
        seen.add(key)
        payload = "\n".join(lines[timing_line + 1:])
        cues.append(SubtitleCue(key, start, end,
                                unescape(payload) if kind == "vtt" else payload))
    return cues
