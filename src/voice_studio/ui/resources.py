from __future__ import annotations

"""Bundled assets work in source checkouts and frozen PyInstaller builds."""

from pathlib import Path
import sys

def _resource_path(filename: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[3]))
    return base / "assets" / filename
