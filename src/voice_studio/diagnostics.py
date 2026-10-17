"""Platform-native preflight; does not download media, models or dependencies."""
from __future__ import annotations

import importlib
import importlib.util
import json
import platform
import shutil
from pathlib import Path

from .model_registry import descriptors, installed
from .media import ffmpeg_executable

CORE_RUNTIMES = (
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "imageio_ffmpeg",
    "numpy", "scipy", "soundfile", "sherpa_onnx", "faster_whisper", "ctranslate2",
    "huggingface_hub", "torch", "torchaudio", "pyannote.audio",
)


def runtime_presence() -> dict[str, bool]:
    """Cheap startup check; availability is not native/inference readiness."""
    present = {}
    for name in CORE_RUNTIMES:
        try:
            # Looking up a nested module would import its parent.
            present[name] = importlib.util.find_spec(name.split(".")[0]) is not None
        except (ModuleNotFoundError, ValueError):
            present[name] = False
    return present


def runtime_import_errors() -> dict[str, str]:
    """Explicit native import smoke check; never loads or downloads weights."""
    from .runtime import configure_windows_native_runtime
    configure_windows_native_runtime(strict=False)
    errors = {}
    for name in CORE_RUNTIMES:
        try:
            importlib.import_module(name)
        except Exception as exc:
            errors[name] = f"{type(exc).__name__}: {exc}"
    return errors


def diagnose() -> dict:
    checks: dict = {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "runtime": runtime_presence(),
        "models": {},
    }
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
        "Diarization consumes FFmpeg-normalized PCM tensors; TorchCodec file decoding is not used.",
    ]
    return checks

def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-runtimes", action="store_true", help="Import all required native backends (no models/network)")
    args = parser.parse_args()
    checks = diagnose()
    if args.check_runtimes:
        checks["runtime_import_errors"] = runtime_import_errors()
    print(json.dumps(checks, indent=2))
    if args.check_runtimes and checks["runtime_import_errors"]:
        raise SystemExit(1)

if __name__ == "__main__":
    main()
