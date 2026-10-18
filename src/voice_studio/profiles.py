from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import MODEL_DIR
from .model_catalog import default_model, descriptors


@dataclass(frozen=True)
class InferenceProfile:
    """User-facing inference preset backed by one downloadable embedding model."""

    key: str
    label: str
    description: str
    model_filename: str
    model_size: int
    model_sha256: str
    download_urls: tuple[str, ...]
    default_threshold: float
    num_threads: int = 2

    @property
    def model_path(self) -> Path:
        from .model_service import ModelService
        model = next(entry for entry in descriptors("locator") if entry.profile_key == self.key)
        return ModelService().path(model)


DEFAULT_PROFILE_KEY = default_model("locator").profile_key

INFERENCE_PROFILES: dict[str, InferenceProfile] = {
    model.profile_key: InferenceProfile(
        key=model.profile_key,
        label=model.label,
        description=model.description,
        model_filename=model.required_assets[0],
        model_size=model.expected_size_bytes,
        model_sha256=model.sha256,
        download_urls=model.download_urls,
        default_threshold=model.inference_defaults.threshold,
        num_threads=model.inference_defaults.num_threads,
    )
    for model in descriptors("locator")
}


def get_inference_profile(profile_key: str | None = None) -> InferenceProfile:
    key = (profile_key or DEFAULT_PROFILE_KEY).strip().lower()
    try:
        return INFERENCE_PROFILES[key]
    except KeyError as exc:
        choices = ", ".join(INFERENCE_PROFILES)
        raise ValueError(f"Invalid inference profile: {profile_key!r}. Choose one of: {choices}.") from exc
