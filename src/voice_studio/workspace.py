"""Portable project storage; runtime/model resources have a separate root."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path


def application_directory() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def projects_directory() -> Path:
    """Check actual write access, with no cwd/profile fallback."""
    root = application_directory()
    directory = root / ".projects"
    try:
        # Check the app folder as well: an existing writable .projects directory
        # must not disguise an unsupported read-only portable installation.
        with tempfile.TemporaryFile(dir=root):
            pass
        directory.mkdir(exist_ok=True)
        with tempfile.TemporaryFile(dir=directory):
            pass
    except OSError as exc:
        raise OSError(
            f"The portable app folder must be writable: {root}. "
            "Move/extract Voice Studio to a writable folder, for example "
            r"D:\VoiceStudio\, and keep its .projects folder alongside the executable. "
            "Projects will not be redirected to AppData or your home folder."
        ) from exc
    return directory
