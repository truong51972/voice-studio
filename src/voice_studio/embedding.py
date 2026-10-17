from __future__ import annotations

from pathlib import Path

import numpy as np

from .runtime import configure_windows_native_runtime


class SpeakerEmbedder:
    """Thin wrapper over sherpa-onnx's speaker embedding extractor."""

    def __init__(self, model_path: Path, num_threads: int = 2) -> None:
        if not model_path.is_file():
            raise FileNotFoundError(
                f"Không tìm thấy speaker model: {model_path}. Chạy `poe models` trước."
            )

        # Must happen before importing sherpa_onnx on Windows. It prevents an old
        # system-wide onnxruntime.dll (e.g. ORT 1.17.1) from overriding the runtime
        # that was built for the installed sherpa-onnx version.
        configure_windows_native_runtime(strict=True)

        try:
            import sherpa_onnx
        except ImportError as exc:
            raise RuntimeError(
                "Thiếu dependency sherpa-onnx. Chạy `uv sync --dev` trước."
            ) from exc

        try:
            config = sherpa_onnx.SpeakerEmbeddingExtractorConfig(
                model=str(model_path),
                num_threads=num_threads,
                debug=False,
                provider="cpu",
            )
            if not config.validate():
                raise RuntimeError(f"Sherpa speaker model config không hợp lệ: {model_path}")
            self.extractor = sherpa_onnx.SpeakerEmbeddingExtractor(config)
        except Exception as exc:
            message = str(exc)
            if "requested API version" in message.lower() or "current ort version" in message.lower():
                raise RuntimeError(
                    "ONNX Runtime đang bị xung đột phiên bản trên Windows. "
                    "Ứng dụng đã cố ưu tiên DLL đi kèm sherpa-onnx nhưng runtime vẫn không tương thích. "
                    "Hãy build lại từ source mới bằng `uv sync --dev` rồi `uv run poe build`. "
                    f"Chi tiết gốc: {message}"
                ) from exc
            raise

    @property
    def dim(self) -> int:
        return int(self.extractor.dim)

    def compute(self, samples: np.ndarray, sample_rate: int = 16_000) -> np.ndarray:
        samples = np.ascontiguousarray(samples, dtype=np.float32)
        stream = self.extractor.create_stream()
        stream.accept_waveform(sample_rate=sample_rate, waveform=samples)
        stream.input_finished()
        if not self.extractor.is_ready(stream):
            raise ValueError("Đoạn giọng nói quá ngắn để tạo speaker embedding.")
        embedding = np.asarray(self.extractor.compute(stream), dtype=np.float32)
        norm = float(np.linalg.norm(embedding))
        if norm <= 1e-12:
            raise ValueError("Không thể tạo embedding hợp lệ từ đoạn âm thanh này.")
        return embedding / norm
