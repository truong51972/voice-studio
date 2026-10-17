"""Validated, data-only model definitions shared by source and frozen builds."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Annotated, Literal, Self
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ModelTask = Literal["locator", "stt", "diarization"]
ModelEngine = Literal["sherpa-onnx", "faster-whisper", "pyannote"]
Identifier = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9_-]*$")]


class InferenceDefaults(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    device: Literal["cpu", "cuda"] = "cpu"
    threshold: float | None = Field(default=None, ge=0, le=1)
    num_threads: int = Field(default=2, ge=1, le=64)
    language: Literal["auto", "vi", "en"] = "auto"
    compute_type: Literal["int8", "float32", "float16", "int8_float16"] = "int8"
    vad: bool = True
    word_timestamps: bool = False
    chunk_seconds: int = Field(default=30, ge=5, le=60)


class ModelDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: Identifier
    task: ModelTask
    engine: ModelEngine
    label: str = Field(min_length=1)
    source: str = Field(min_length=1)
    provider: Literal["urls", "huggingface", "local-folder"]
    license: str = Field(min_length=1)
    languages: tuple[str, ...] = Field(min_length=1)
    devices: tuple[Literal["cpu", "cuda"], ...] = Field(min_length=1)
    required_assets: tuple[str, ...] = Field(min_length=1)
    expected_size_bytes: int | None = Field(default=None, gt=0)
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    revision: str | None = Field(default=None, min_length=1)
    download_urls: tuple[str, ...] = ()
    profile_key: Identifier | None = None
    description: str = ""
    access: str = "Public model; review the upstream license before installing."
    capabilities: tuple[Literal[
        "offline", "word_timestamps", "vad", "speaker_embeddings", "anonymous_speakers",
    ], ...] = ()
    default: bool = False
    inference_defaults: InferenceDefaults = InferenceDefaults()

    @field_validator("required_assets")
    @classmethod
    def safe_assets(cls, assets: tuple[str, ...]) -> tuple[str, ...]:
        for asset in assets:
            parts = PurePosixPath(asset).parts
            if (not parts or asset != PurePosixPath(asset).as_posix()
                    or PurePosixPath(asset).is_absolute() or PureWindowsPath(asset).drive
                    or ".." in parts or "\\" in asset or ":" in asset
                    or any(ord(char) < 32 for char in asset)):
                raise ValueError(f"Unsafe model asset path: {asset!r}")
        if len(set(assets)) != len(assets):
            raise ValueError("Duplicate required asset paths")
        return assets

    @field_validator("download_urls")
    @classmethod
    def https_urls(cls, urls: tuple[str, ...]) -> tuple[str, ...]:
        if any(urlsplit(url).scheme != "https" or not urlsplit(url).netloc
               or urlsplit(url).username is not None for url in urls):
            raise ValueError("Model download sources must be HTTPS URLs without credentials")
        return urls

    @model_validator(mode="after")
    def supported_backend(self) -> Self:
        if self.inference_defaults.device not in self.devices:
            raise ValueError("Default device must be supported by the model")
        if self.engine == "sherpa-onnx":
            if (self.task != "locator" or self.provider != "urls" or not self.profile_key
                    or len(self.required_assets) != 1 or "/" in self.required_assets[0]
                    or not self.sha256 or not self.expected_size_bytes or not self.download_urls
                    or self.inference_defaults.threshold is None):
                raise ValueError("sherpa-onnx needs a Locator profile, one file, mirrors, size, SHA-256 and threshold")
        else:
            expected = ("stt", "huggingface") if self.engine == "faster-whisper" else ("diarization", "local-folder")
            if (self.task, self.provider) != expected or not self.revision or self.profile_key:
                raise ValueError(f"{self.engine} needs task/provider {expected} and a source revision")
            if len(self.source.split("/")) != 2 or any(
                not part or part in (".", "..") or not all(c.isalnum() or c in "-_." for c in part)
                for part in self.source.split("/")
            ):
                raise ValueError("Hugging Face source must be an owner/repository ID")
            if self.engine == "faster-whisper":
                if not {"model.bin", "config.json", "tokenizer.json"}.issubset(self.required_assets):
                    raise ValueError("faster-whisper needs model.bin, config.json and tokenizer.json")
                if self.inference_defaults.language not in self.languages:
                    raise ValueError("Default language must be supported by the model")
            elif "config.yaml" not in self.required_assets:
                raise ValueError("pyannote needs a local config.yaml")
        return self


class CatalogFile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    models: tuple[ModelDescriptor, ...] = Field(min_length=1)


class CatalogError(ValueError):
    """A shipped catalog is missing or invalid; includes its filename."""


def catalog_directory() -> Path:
    # Wheel and PyInstaller data live inside the package. A checkout uses the
    # same files via Hatch's force-include mapping, without a second source copy.
    bundled = Path(__file__).resolve().parent / "configs" / "models"
    return bundled if bundled.is_dir() else Path(__file__).resolve().parents[2] / "configs" / "models"


def load_catalog(directory: Path) -> tuple[ModelDescriptor, ...]:
    models: list[ModelDescriptor] = []
    for filename, task in (("speaker_matching.json", "locator"), ("stt.json", "stt"), ("diarization.json", "diarization")):
        path = directory / filename
        try:
            entries = CatalogFile.model_validate_json(path.read_text(encoding="utf-8")).models
            if any(model.task != task for model in entries):
                raise ValueError(f"Every model in {filename} must have task {task!r}")
            if sum(model.default for model in entries) != 1:
                raise ValueError("Each task must have exactly one default model")
            models.extend(entries)
        except (OSError, ValueError) as exc:
            raise CatalogError(f"Invalid model catalog {path}: {exc}") from exc
    ids = [model.id for model in models]
    profiles = [model.profile_key for model in models if model.profile_key]
    if len(set(ids)) != len(ids) or len(set(profiles)) != len(profiles):
        raise CatalogError(f"Invalid model catalog {directory}: duplicate model ID or profile key")
    return tuple(models)


def descriptors(task: ModelTask | None = None) -> tuple[ModelDescriptor, ...]:
    return tuple(model for model in _catalog() if task is None or model.task == task)


@lru_cache(maxsize=1)
def _catalog() -> tuple[ModelDescriptor, ...]:
    # Only the shipped catalog is cached; arbitrary test/import directories are not.
    return load_catalog(catalog_directory())


def get_model(model_id: str) -> ModelDescriptor:
    for model in descriptors():
        if model.id == model_id:
            return model
    raise KeyError(f"Unknown model: {model_id}")


def default_model(task: ModelTask) -> ModelDescriptor:
    return next(model for model in descriptors(task) if model.default)
