"""Task-aware model catalog; no heavy backend imports at application startup.

Locator profiles preserve upstream size/SHA-256. STT assets are installed into a
user-writable directory from immutable Hugging Face snapshot revisions. A
manifest records each installed artifact's local digest (not a claim that the
publisher supplied trusted hashes).
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

from .model_catalog import ModelDescriptor, ModelTask, descriptors, get_model

def user_model_dir() -> Path:
    override = os.environ.get("VOICE_STUDIO_MODEL_DIR")
    if override:
        return Path(override).expanduser()
    if sys.platform == "win32":
        root = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(root) / "VoiceStudio" / "models"
    return Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))) / "voice-studio" / "models"

def model_path(model: ModelDescriptor, root: Path | None = None) -> Path:
    if model.task == "locator":
        from .profiles import get_inference_profile
        return ((root / model.required_assets[0]) if root is not None
                else get_inference_profile(model.profile_key).model_path)
    return (root if root is not None else user_model_dir()) / model.id

def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

def installed(model: ModelDescriptor, root: Path | None = None) -> bool:
    path = model_path(model, root)
    if model.task == "locator":
        file = path
        return file.is_file() and file.stat().st_size == model.expected_size_bytes and _digest(file) == model.sha256
    manifest = path / "voice-studio-manifest.json"
    if not manifest.is_file():
        return False
    try:
        record = json.loads(manifest.read_text(encoding="utf-8"))
        checksums = record["sha256"]
        if record["id"] != model.id or not record.get("resolved_revision"):
            return False
        if any(asset not in checksums for asset in model.required_assets):
            return False
        return all(
            not Path(name).is_absolute()
            and ".." not in Path(name).parts
            and (path / name).is_file()
            and _digest(path / name) == expected
            for name, expected in checksums.items()
        )
    except (ValueError, OSError, KeyError, TypeError):
        return False

def preflight(model: ModelDescriptor, *, device: str = "cpu", root: Path | None = None) -> list[str]:
    problems = []
    if device not in model.devices:
        problems.append(f"{model.label}: device {device!r} is unsupported")
    if model.engine == "faster-whisper" and importlib.util.find_spec("faster_whisper") is None:
        problems.append("STT runtime is missing. Repair the application installation.")
    if model.engine == "pyannote":
        problems.append(model.access)
    if model.engine == "sherpa-onnx" and importlib.util.find_spec("sherpa_onnx") is None:
        problems.append("Speaker runtime is missing. Repair the application installation.")
    if not installed(model, root):
        problems.append(f"Model not installed or corrupt: {model.id}")
    if device == "cuda":
        # Native DLL/driver compatibility cannot be inferred from Python imports.
        problems.append("CUDA compatibility requires a real CTranslate2 runtime smoke test; select CPU unless verified")
    return problems

def install(model: ModelDescriptor, root: Path | None = None) -> Path:
    """Explicit, blocking installer to call from a worker, never the GUI thread."""
    if model.task == "locator":
        from .model_download import ensure_model
        from .profiles import get_inference_profile
        ensure_model(get_inference_profile(model.profile_key), model_path(model, root))
        if not installed(model, root):
            raise RuntimeError("Locator download failed integrity verification")
        return model_path(model, root)

    if model.provider == "local-folder":
        raise RuntimeError(model.access)
    if importlib.util.find_spec("huggingface_hub") is None:
        raise RuntimeError("Model download runtime is missing. Repair the application installation.")
    from huggingface_hub import HfApi, snapshot_download

    base = root if root is not None else user_model_dir()
    base.mkdir(parents=True, exist_ok=True)
    destination = model_path(model, base)
    if installed(model, base):
        return destination
    if destination.exists():
        raise RuntimeError(f"Existing incomplete model directory: {destination}. Remove through Model Manager and retry")
    # Resolve revision first, then fetch immutable commit; do not silently switch revisions.
    revision = HfApi().model_info(model.source, revision=model.revision or "main").sha
    if not revision or len(revision) < 16:
        raise RuntimeError("Could not resolve model snapshot revision")
    scratch = Path(tempfile.mkdtemp(prefix=f".{model.id}-", dir=base))
    try:
        snapshot = Path(snapshot_download(
            repo_id=model.source, revision=revision,
            allow_patterns=["*.json", "*.txt", "*.bin", "*.model"],
        ))
        for asset in model.required_assets:
            if not (snapshot / asset).is_file():
                raise RuntimeError(f"Missing required model artifact: {asset}")
        checksums = {}
        for src in snapshot.rglob("*"):
            if not src.is_file():
                continue
            relative = src.relative_to(snapshot)
            dst = scratch / relative
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
            checksums[relative.as_posix()] = _digest(dst)
        metadata = {
            "id": model.id, "source": model.source,
            "resolved_revision": revision, "sha256": checksums,
        }
        (scratch / "voice-studio-manifest.json").write_text(
            json.dumps(metadata, indent=2), encoding="utf-8"
        )
        if not installed(model, scratch.parent) and not _verify_tree(scratch, model):
            raise RuntimeError("Model download is incomplete or failed verification")
        scratch.rename(destination)
        return destination
    finally:
        if scratch.exists():
            shutil.rmtree(scratch)

def _verify_tree(directory: Path, model: ModelDescriptor) -> bool:
    return all((directory / asset).is_file() for asset in model.required_assets)

def uninstall(model: ModelDescriptor, root: Path | None = None) -> None:
    path = model_path(model, root)
    if model.task == "locator":
        if getattr(sys, "frozen", False):
            raise RuntimeError("Bundled Locator model cannot be removed from a packaged app")
        path.unlink(missing_ok=True)
    elif path.is_dir():
        shutil.rmtree(path)
