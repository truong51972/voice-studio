"""Portable, Qt-independent model lifecycle. No network or hashing on status reads."""
from __future__ import annotations

import fnmatch
import hashlib
import importlib.metadata
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from threading import Event
from typing import Callable
from urllib.request import Request, urlopen

from filelock import FileLock, Timeout

from .model_catalog import ModelDescriptor, default_model, descriptors, get_model
from .storage import application_dir, atomic_json, read_json

MANIFEST = "voice-studio-manifest.json"
CATEGORIES = {"locator": "speaker_matching", "stt": "stt", "diarization": "diarization"}
Progress = Callable[[str, int, int, float], None]


class Cancelled(RuntimeError):
    pass


def check_cancel(cancel: Event | None) -> None:
    if cancel is not None and cancel.is_set():
        raise Cancelled("Cancelled. Partial downloads are retained for Retry.")


def safe_asset(directory: Path, name: str) -> Path:
    parts = PurePosixPath(name).parts
    if (not parts or name != PurePosixPath(name).as_posix() or name.startswith("/")
            or ".." in parts or "\\" in name or ":" in name
            or PureWindowsPath(name).drive or any(ord(c) < 32 for c in name)):
        raise ValueError(f"Unsafe artifact path: {name!r}")
    candidate = directory / name
    if not candidate.resolve().is_relative_to(directory.resolve()):
        raise ValueError(f"Artifact leaves model folder: {name}")
    return candidate


def digest(path: Path, cancel: Event | None = None) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            check_cancel(cancel)
            result.update(chunk)
    return result.hexdigest()


@dataclass(frozen=True)
class ModelStatus:
    state: str
    path: Path
    detail: str = ""
    verified: bool = False
    ready: bool = False


class ModelService:
    def __init__(self, root: Path | None = None, *, settings: Path | None = None):
        self.settings = settings if settings is not None else application_dir() / ".settings" / "models.json"
        preferences = read_json(self.settings)
        configured = root or os.environ.get("VOICE_STUDIO_MODEL_DIR") or preferences.get("storage")
        self.root = Path(configured).expanduser().resolve() if configured else application_dir() / ".models"

    def preferences(self) -> dict:
        return read_json(self.settings)

    def default_id(self, task: str) -> str:
        selected = self.preferences().get("defaults", {}).get(task, default_model(task).id)
        return selected if any(m.id == selected and m.task == task for m in descriptors()) else default_model(task).id

    def set_default(self, model: ModelDescriptor) -> None:
        data = self.preferences()
        data.setdefault("defaults", {})[model.task] = model.id
        atomic_json(self.settings, data)

    def set_storage(self, path: Path) -> None:
        for model in descriptors():
            if self.busy(model):
                raise RuntimeError("Finish or cancel model operations/jobs before changing storage.")
        path = path.expanduser().resolve()
        for protected in (application_dir() / ".projects", application_dir() / ".settings"):
            if path == protected or path.is_relative_to(protected):
                raise ValueError("Choose a model directory outside projects and settings.")
        path.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=path):
            pass
        data = self.preferences()
        data["storage"] = str(path)
        atomic_json(self.settings, data)
        self.root = path

    def owned_dir(self, model: ModelDescriptor) -> Path:
        category = self.root / CATEGORIES[model.task]
        path = category / model.id
        if category.is_symlink() or path.is_symlink() or not path.resolve().is_relative_to(self.root.resolve()):
            raise ValueError("Managed model path leaves storage or is a symlink. Use explicit Import instead.")
        return path

    def directory(self, model: ModelDescriptor) -> Path:
        external = self.preferences().get("imports", {}).get(model.id)
        return Path(external) if external else self.owned_dir(model)

    def path(self, model: ModelDescriptor) -> Path:
        directory = self.directory(model)
        return directory / model.required_assets[0] if model.task == "locator" else directory

    def manifest_path(self, model: ModelDescriptor) -> Path:
        if model.id in self.preferences().get("imports", {}):
            return self.settings.parent / "manifests" / f"{model.id}.json"
        return self.owned_dir(model) / MANIFEST

    def _record(self, model: ModelDescriptor) -> dict:
        record = read_json(self.manifest_path(model))
        if (record.get("schema_version") != 1 or record.get("id") != model.id
                or record.get("engine") != model.engine or record.get("source") != model.source
                or not isinstance(record.get("resolved_revision"), str)
                or not record["resolved_revision"] or not isinstance(record.get("files"), dict)):
            raise ValueError("Missing or inconsistent manifest. Import or repair this model.")
        if not set(model.required_assets).issubset(record["files"]):
            raise ValueError("Manifest is missing required assets.")
        directory = self.directory(model)
        for name, entry in record["files"].items():
            safe_asset(directory, name)
            if (not isinstance(entry, dict) or type(entry.get("size")) is not int
                    or entry["size"] <= 0 or not re.fullmatch(r"[0-9a-f]{64}", str(entry.get("sha256")))
                    or type(entry.get("mtime_ns")) is not int):
                raise ValueError(f"Invalid artifact metadata: {name}")
        if model.task == "locator":
            artifact = record["files"][model.required_assets[0]]
            if artifact["size"] != model.expected_size_bytes or artifact["sha256"] != model.sha256:
                raise ValueError("Manifest does not match publisher size/SHA-256.")
        return record

    def status(self, model: ModelDescriptor) -> ModelStatus:
        path = self.path(model)
        try:
            if not self.directory(model).exists():
                return ModelStatus("Not installed", path)
            record = self._record(model)
            for name, entry in record["files"].items():
                file = safe_asset(self.directory(model), name)
                stat = file.stat()
                if not file.is_file() or stat.st_size != entry["size"] or stat.st_mtime_ns != entry["mtime_ns"]:
                    raise ValueError(f"Changed or incomplete asset: {name}. Verify or repair.")
            ready = record.get("ready") == self.runtime_signature(model)
            return ModelStatus("Ready" if ready else "Installed", path,
                               record.get("readiness_error", "Integrity verified locally; readiness needs a model-load test."),
                               verified=bool(record.get("verified_at")), ready=ready)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            return ModelStatus("Incomplete", path, str(exc))

    @staticmethod
    def runtime_signature(model: ModelDescriptor, device: str = "cpu", compute_type: str | None = None) -> dict:
        package = {"sherpa-onnx": "sherpa-onnx", "faster-whisper": "faster-whisper", "pyannote": "pyannote.audio"}[model.engine]
        try:
            version = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            version = "missing"
        return {"engine": model.engine, "version": version, "python": sys.version.split()[0],
                "device": device, "compute_type": compute_type or model.inference_defaults.compute_type}

    def preflight(self, model: ModelDescriptor, *, device: str = "cpu") -> list[str]:
        state = self.status(model)
        errors = []
        if device not in model.devices:
            errors.append(f"Unsupported device: {device}")
        if state.state not in ("Installed", "Ready"):
            errors.append(f"{model.label}: {state.state.lower()}. Open Settings → Models to install, import or repair. {state.detail}")
        elif not state.ready:
            errors.append(f"{model.label}: run Test readiness in Settings → Models before queueing.")
        if device != "cpu":
            errors.append("CUDA requires a separate native inference test; CPU is the supported baseline.")
        return errors

    def _lock(self, model: ModelDescriptor) -> FileLock:
        directory = self.root / ".locks"
        if directory.is_symlink():
            raise ValueError("Model lock directory cannot be a symlink.")
        directory.mkdir(parents=True, exist_ok=True)
        return FileLock(directory / f"{model.id}.lock", timeout=0)

    @contextmanager
    def use(self, model: ModelDescriptor):
        try:
            with self._lock(model):
                yield
        except Timeout as exc:
            raise RuntimeError(f"{model.label} is in use. Finish or cancel its job first.") from exc

    def busy(self, model: ModelDescriptor) -> bool:
        if not (self.root / ".locks").exists():
            return False
        try:
            with self._lock(model):
                return False
        except Timeout:
            return True

    def discover(self, model: ModelDescriptor) -> tuple[Path, ...]:
        """Read-only discovery. Never moves, copies, registers or deletes legacy data."""
        from .config import PROJECT_ROOT
        candidates = [PROJECT_ROOT / "models"] if model.task == "locator" else []
        if model.task == "stt":
            local = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "VoiceStudio" / "models"
            xdg = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))) / "voice-studio" / "models"
            candidates.extend((local / model.id, xdg / model.id, self.root / model.id))
        return tuple(path for path in candidates if all((path / name).is_file() for name in model.required_assets))

    def _scan(self, model: ModelDescriptor, directory: Path, revision: str, *, cancel=None, progress=None) -> dict:
        for name in model.required_assets:
            file = safe_asset(directory, name)
            if not file.is_file() or not file.stat().st_size:
                raise ValueError(f"Missing or empty required asset: {name}")
        if model.task == "diarization":
            from .model_backends import community_config
            community_config(directory)
        files = {}
        paths = [safe_asset(directory, model.required_assets[0])] if model.task == "locator" else [
            path for path in directory.rglob("*") if path.is_file() and path.name != MANIFEST and ".cache" not in path.relative_to(directory).parts
        ]
        total = sum(path.stat().st_size for path in paths)
        done = 0
        for path in paths:
            check_cancel(cancel)
            name = path.relative_to(directory).as_posix()
            safe_asset(directory, name)
            before = path.stat()
            checksum = digest(path, cancel)
            after = path.stat()
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise ValueError(f"Artifact changed during verification: {name}")
            if model.task == "locator" and (before.st_size != model.expected_size_bytes or checksum != model.sha256):
                raise ValueError("Speaker model failed publisher size/SHA-256 verification.")
            files[name] = {"size": after.st_size, "sha256": checksum, "mtime_ns": after.st_mtime_ns}
            done += after.st_size
            if progress:
                progress("Verifying " + name, done, total, 0)
        return {"schema_version": 1, "id": model.id, "engine": model.engine,
                "source": model.source, "resolved_revision": revision, "files": files,
                "verified_at": time.time(), "provenance": "Local hashes are not publisher signatures."}

    def import_local(self, model: ModelDescriptor, directory: Path, *, cancel=None, progress=None) -> None:
        directory = directory.expanduser().resolve()
        if not directory.is_dir():
            raise ValueError("Select a complete model directory.")
        with self.use(model):
            record = self._scan(model, directory, "local:" + str(directory), cancel=cancel, progress=progress)
            atomic_json(self.settings.parent / "manifests" / f"{model.id}.json", record)
            data = self.preferences()
            data.setdefault("imports", {})[model.id] = str(directory)
            atomic_json(self.settings, data)

    def verify(self, model: ModelDescriptor, *, cancel=None, progress=None) -> None:
        with self.use(model):
            record = self._record(model)
            for name, metadata in record["files"].items():
                check_cancel(cancel)
                if progress:
                    progress("Verifying " + name, 0, 0, 0)
                file = safe_asset(self.directory(model), name)
                if not file.is_file() or file.stat().st_size != metadata["size"] or digest(file, cancel) != metadata["sha256"]:
                    record.pop("ready", None)
                    record.pop("verified_at", None)
                    record["integrity_error"] = name
                    record["readiness_error"] = f"Integrity check failed: {name}. Repair or reimport."
                    atomic_json(self.manifest_path(model), record)
                    raise ValueError(record["readiness_error"])
                metadata["mtime_ns"] = file.stat().st_mtime_ns
            record["verified_at"] = time.time()
            record.pop("integrity_error", None)
            atomic_json(self.manifest_path(model), record)

    def ready(self, model: ModelDescriptor, *, cancel=None, progress=None) -> None:
        self.verify(model, cancel=cancel, progress=progress)
        with self.use(model):
            record = self._record(model)
            record.pop("ready", None)
            atomic_json(self.manifest_path(model), record)
            command = ([sys.executable, "--model-probe"] if getattr(sys, "frozen", False)
                       else [sys.executable, "-m", "voice_studio.model_backends"])
            command += [model.id, str(self.path(model))]
            if progress:
                progress("Loading model and running CPU smoke test…", 0, 0, 0)
            environment = dict(os.environ, HF_HUB_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1", PYANNOTE_METRICS_ENABLED="0")
            with tempfile.TemporaryFile(mode="w+b") as output:
                process = subprocess.Popen(command, stdout=output, stderr=output, env=environment)
                try:
                    start = time.monotonic()
                    while process.poll() is None:
                        check_cancel(cancel)
                        if time.monotonic() - start > 300:
                            raise RuntimeError("Model-load test timed out after five minutes.")
                        time.sleep(.1)
                    if process.returncode:
                        output.seek(0)
                        raise RuntimeError(output.read().decode(errors="replace")[-3000:] or "Model-load subprocess failed.")
                except BaseException as exc:
                    process.kill()
                    process.wait()
                    record["readiness_error"] = str(exc)
                    atomic_json(self.manifest_path(model), record)
                    raise
            record["ready"] = self.runtime_signature(model)
            record.pop("readiness_error", None)
            atomic_json(self.manifest_path(model), record)

    def install(self, model: ModelDescriptor, *, cancel=None, progress=None) -> Path:
        if model.provider == "local-folder":
            raise ValueError(model.access + " Use Import local folder.")
        with self.use(model):
            if model.id in self.preferences().get("imports", {}):
                raise ValueError("This model uses an external folder. Unlink it before installing a managed copy.")
            destination = self.owned_dir(model)
            scratch = destination.with_name("." + model.id + ".partial")
            if scratch.is_symlink():
                raise ValueError("Partial download folder cannot be a symlink.")
            scratch.mkdir(parents=True, exist_ok=True)
            if model.provider == "urls":
                revision = "sha256:" + model.sha256
                assets = [(model.required_assets[0], model.expected_size_bytes, model.download_urls, model.sha256)]
            else:
                from huggingface_hub import HfApi, hf_hub_url
                info = HfApi().model_info(model.source, revision=model.revision, files_metadata=True)
                if not re.fullmatch(r"[0-9a-f]{40,64}", str(info.sha)):
                    raise ValueError("Provider did not resolve an immutable model revision.")
                revision = info.sha
                assets = []
                for entry in info.siblings:
                    name = entry.rfilename
                    if any(fnmatch.fnmatch(name, pattern) for pattern in ("*.json", "*.txt", "*.bin", "*.model")):
                        safe_asset(scratch, name)
                        if not entry.size or entry.size < 0:
                            raise ValueError(f"Provider did not report artifact size: {name}")
                        lfs = getattr(entry, "lfs", None)
                        checksum = getattr(lfs, "sha256", None) if lfs else None
                        assets.append((name, entry.size, (hf_hub_url(model.source, name, revision=revision),), checksum))
                if not set(model.required_assets).issubset({asset[0] for asset in assets}):
                    raise ValueError("Provider snapshot lacks required assets.")
            marker = scratch / ".revision"
            if marker.exists() and marker.read_text() != revision:
                shutil.rmtree(scratch)
                scratch.mkdir()
            marker.write_text(revision)
            total = sum(asset[1] for asset in assets)
            done = 0
            started = time.monotonic()
            for name, size, urls, checksum in assets:
                target = safe_asset(scratch, name)
                target.parent.mkdir(parents=True, exist_ok=True)
                def report(stage, count, _total, _speed):
                    if progress:
                        progress(stage, done + count, total, (done + count) / max(time.monotonic() - started, .001))
                download_file(urls, target, size, checksum, cancel=cancel, progress=report)
                done += size
            marker.unlink(missing_ok=True)
            record = self._scan(model, scratch, revision, cancel=cancel, progress=progress)
            atomic_json(scratch / MANIFEST, record)
            check_cancel(cancel)
            backup = destination.with_name("." + model.id + ".previous")
            if backup.is_symlink():
                raise ValueError("Previous installation folder cannot be a symlink.")
            if backup.exists():
                if not destination.exists():
                    backup.rename(destination)
                else:
                    shutil.rmtree(backup)
            if destination.exists():
                destination.rename(backup)
            try:
                scratch.rename(destination)
            except BaseException:
                if backup.exists():
                    backup.rename(destination)
                raise
            if backup.exists():
                shutil.rmtree(backup)
            return self.path(model)

    def remove(self, model: ModelDescriptor) -> None:
        with self.use(model):
            data = self.preferences()
            if model.id in data.get("imports", {}):
                del data["imports"][model.id]
                atomic_json(self.settings, data)
                (self.settings.parent / "manifests" / f"{model.id}.json").unlink(missing_ok=True)
                return
            for folder in (self.owned_dir(model), self.owned_dir(model).with_name("." + model.id + ".partial")):
                if folder.is_symlink() or not folder.resolve().is_relative_to(self.root.resolve()):
                    raise ValueError("Refusing to remove a model outside managed storage.")
                if folder.exists():
                    shutil.rmtree(folder)


def download_file(urls, destination: Path, size: int, checksum: str | None, *, cancel=None, progress=None) -> None:
    """Bounded HTTP streaming, Range resume, retry/fallback, validated atomic file promotion."""
    if destination.is_file() and destination.stat().st_size == size and (not checksum or digest(destination, cancel) == checksum):
        return
    partial = destination.with_name(destination.name + ".part")
    failures = []
    for url in urls:
        for _attempt in range(2):
            check_cancel(cancel)
            try:
                offset = partial.stat().st_size if partial.exists() else 0
                if offset >= size:
                    partial.unlink()
                    offset = 0
                headers = {"User-Agent": "VoiceStudio/0.1"}
                if offset:
                    headers["Range"] = f"bytes={offset}-"
                with urlopen(Request(url, headers=headers), timeout=15) as response:
                    append = offset > 0 and response.status == 206
                    if append and not response.headers.get("Content-Range", "").startswith(f"bytes {offset}-"):
                        raise ValueError("Server returned an inconsistent resume range.")
                    if not append:
                        offset = 0
                    with partial.open("ab" if append else "wb") as stream:
                        while True:
                            check_cancel(cancel)
                            chunk = response.read(1024 * 1024)
                            if not chunk:
                                break
                            stream.write(chunk)
                            offset += len(chunk)
                            if offset > size:
                                raise ValueError("Download exceeds provider artifact size.")
                            if progress:
                                progress("Downloading " + destination.name, offset, size, 0)
                if offset != size:
                    raise OSError(f"Incomplete transfer ({offset}/{size} bytes). Retry to resume.")
                if checksum and digest(partial, cancel) != checksum:
                    partial.unlink()
                    raise ValueError("Downloaded artifact failed SHA-256 verification.")
                partial.replace(destination)
                return
            except Cancelled:
                raise
            except (OSError, ValueError) as exc:
                failures.append(str(exc))
    raise RuntimeError("Download failed; Retry resumes partial files. " + "; ".join(failures))
