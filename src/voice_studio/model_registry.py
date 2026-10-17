"""Compatibility interface backed by the unified portable model service."""
from pathlib import Path

from .model_catalog import ModelDescriptor, ModelTask, descriptors, get_model
from .model_service import ModelService


def user_model_dir() -> Path:
    return ModelService().root


def model_path(model: ModelDescriptor, root: Path | None = None) -> Path:
    return ModelService(root).path(model)


def installed(model: ModelDescriptor, root: Path | None = None) -> bool:
    return ModelService(root).status(model).state in ("Installed", "Ready")


def preflight(model: ModelDescriptor, *, device: str = "cpu", compute_type: str | None = None,
              root: Path | None = None) -> list[str]:
    return ModelService(root).preflight(model, device=device, compute_type=compute_type)


def install(model: ModelDescriptor, root: Path | None = None) -> Path:
    return ModelService(root).install(model)


def uninstall(model: ModelDescriptor, root: Path | None = None) -> None:
    ModelService(root).remove(model)
