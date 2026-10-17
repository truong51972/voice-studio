"""Platform-native preflight; does not download media, models or dependencies."""
from __future__ import annotations

import importlib.util
import json
import platform
import shutil
from pathlib import Path

from .model_registry import descriptors, installed
from .media import ffmpeg_executable


def diagnose() -> dict:
    checks: dict = {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "runtime": {},
        "models": {},
    }
    for name in ("PySide6", "sherpa_onnx", "faster_whisper", "ctranslate2", "pyannote.audio"):
        try:
            checks["runtime"][name] = importlib.util.find_spec(name) is not None
        except (ModuleNotFoundError, ValueError):
            checks["runtime"][name] = False
    try:
        executable = ffmpeg_executable()
        checks["ffmpeg"] = {"ok": executable.is_file(), "path": str(executable)}
    except Exception as exc:
        checks["ffmpeg"] = {"ok": False, "error": str(exc)}
    for model in descriptors():
        try:
            checks["models"][model.id] = {
                "installed": installed(model), "task": model.task, "engine": model.engine
            }
        except OSError as exc:
            checks["models"][model.id] = {"installed": False, "error": str(exc)}
    checks["notes"] = [
        "CPU inference requires a smoke test with real installed models.",
        "CUDA drivers, GPU VRAM and CTranslate2 DLLs are not verified by import checks.",
        "No cloud services are used for diagnostics.",
    ]
    return checks

def main() -> None:
    print(json.dumps(diagnose(), indent=2))

if __name__ == "__main__":
    main()
