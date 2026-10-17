from __future__ import annotations

"""Source-relative timestamps are seconds; Qt player boundaries use milliseconds."""

def _fmt_time(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    minutes = int(seconds // 60)
    remain = seconds - minutes * 60
    if minutes:
        return f"{minutes:02d}:{remain:04.1f}"
    return f"{remain:.1f}s"


def _parse_timecode(value: object) -> float:
    text = str(value or "").strip()
    if not text:
        raise ValueError("Timestamp trống.")
    if text.endswith("s"):
        return float(text[:-1])
    if ":" in text:
        minutes, seconds = text.split(":", 1)
        return int(minutes) * 60.0 + float(seconds)
    return float(text)

def seconds_to_milliseconds(seconds: float) -> int:
    """Seek to the nearest whole millisecond, clamping negative timestamps."""
    from math import isfinite

    if not isfinite(seconds):
        raise ValueError("Playback timestamp must be finite")
    return int(max(0.0, seconds) * 1000)


def milliseconds_to_seconds(milliseconds: int) -> float:
    return max(0, milliseconds) / 1000.0
