from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import MODEL_DIR


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
        return MODEL_DIR / self.model_filename


DEFAULT_PROFILE_KEY = "fast"
_RELEASE_BASE = "https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models"
_HF_BASE = "https://huggingface.co/csukuangfj/speaker-embedding-models/resolve/main"

INFERENCE_PROFILES: dict[str, InferenceProfile] = {
    "fast": InferenceProfile(
        key="fast",
        label="Nhanh · CAM++",
        description="Model mặc định, nhẹ hơn và phù hợp phân tích nhanh trên CPU.",
        model_filename="3dspeaker_speech_campplus_sv_en_voxceleb_16k.onnx",
        model_size=29_596_978,
        model_sha256="357a834f702b80161e5b981182c038e18553c1f2ca752ed6cec2052365d4129b",
        download_urls=(
            f"{_RELEASE_BASE}/3dspeaker_speech_campplus_sv_en_voxceleb_16k.onnx",
            f"{_HF_BASE}/3dspeaker_speech_campplus_sv_en_voxceleb_16k.onnx?download=true",
        ),
        default_threshold=0.60,
        num_threads=2,
    ),
    "accurate": InferenceProfile(
        key="accurate",
        label="Chính xác · ERes2NetV2",
        description="Model lớn hơn, ưu tiên chất lượng speaker embedding hơn tốc độ xử lý.",
        model_filename="3dspeaker_speech_eres2netv2_sv_zh-cn_16k-common.onnx",
        model_size=71_441_526,
        model_sha256="bf1a75b9930474cf3389ef415e6e5d38ca96fea4a3a00f7e301d080a58ee2239",
        download_urls=(
            f"{_RELEASE_BASE}/3dspeaker_speech_eres2netv2_sv_zh-cn_16k-common.onnx",
            f"{_HF_BASE}/3dspeaker_speech_eres2netv2_sv_zh-cn_16k-common.onnx?download=true",
        ),
        # Keep the existing threshold as a conservative baseline until the
        # Vietnamese/classroom benchmark calibrates a profile-specific optimum.
        default_threshold=0.60,
        num_threads=2,
    ),
}


def get_inference_profile(profile_key: str | None = None) -> InferenceProfile:
    key = (profile_key or DEFAULT_PROFILE_KEY).strip().lower()
    try:
        return INFERENCE_PROFILES[key]
    except KeyError as exc:
        choices = ", ".join(INFERENCE_PROFILES)
        raise ValueError(f"Inference profile không hợp lệ: {profile_key!r}. Chọn một trong: {choices}.") from exc
