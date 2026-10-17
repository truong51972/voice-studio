"""Explicit, offline backend adapters and isolated model-load smoke entrypoint."""
from __future__ import annotations

import os
from pathlib import Path

from .model_catalog import default_model, get_model


def community_config(directory: Path) -> dict:
    """Accept the standard local Community-1 layout, never arbitrary pipeline code."""
    import yaml
    from .model_service import safe_asset
    model = default_model("diarization")
    for asset in model.required_assets:
        path = safe_asset(directory, asset)
        if not path.is_file() or not path.stat().st_size:
            raise ValueError(f"Incomplete Community-1 folder: missing {asset}")
    config = yaml.safe_load((directory / "config.yaml").read_text(encoding="utf-8"))
    if not isinstance(config, dict) or set(config) - {"version", "dependencies", "pipeline", "params"}:
        raise ValueError("Unsupported Community-1 config. Use an unmodified upstream model folder.")
    pipeline = config.get("pipeline", {})
    if not isinstance(pipeline, dict) or pipeline.get("name") != "pyannote.audio.pipelines.SpeakerDiarization":
        raise ValueError("Only the Community-1 SpeakerDiarization backend is supported.")
    params = dict(pipeline.get("params", {}))
    allowed = {"segmentation", "embedding", "plda", "legacy", "segmentation_step", "embedding_exclude_overlap",
               "clustering", "embedding_batch_size", "segmentation_batch_size", "der_variant"}
    if set(params) - allowed or params.get("clustering", "VBxClustering") not in ("VBxClustering", "AgglomerativeClustering"):
        raise ValueError("Unsupported pipeline parameters in local Community-1 config.")
    for key in ("segmentation", "embedding"):
        params[key] = str(safe_asset(directory, f"{key}/pytorch_model.bin"))
    params["plda"] = str(directory / "plda")
    return {"pipeline": params, "params": config.get("params", {})}


def load_community(directory: Path):
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["PYANNOTE_METRICS_ENABLED"] = "0"
    config = community_config(directory)
    from pyannote.audio.pipelines import SpeakerDiarization
    pipeline = SpeakerDiarization(**config["pipeline"])
    if config["params"]:
        pipeline.instantiate(config["params"])
    return pipeline


_cuda_dll_handles = []


def prepare_cuda_runtime() -> None:
    """Load PyTorch's bundled CUDA libraries before CTranslate2 initializes.

    Windows needs DLL search directories kept alive for the whole process.
    This is not a CUDA readiness guarantee: the native model probe decides.
    """
    import torch
    if os.name == "nt":
        library_dir = Path(torch.__file__).resolve().parent / "lib"
        if library_dir.is_dir():
            os.environ["PATH"] = str(library_dir) + os.pathsep + os.environ.get("PATH", "")
            if hasattr(os, "add_dll_directory"):
                _cuda_dll_handles.append(os.add_dll_directory(str(library_dir)))


def probe(model_id: str, path: Path, device: str = "cpu", compute_type: str | None = None) -> None:
    import numpy as np
    model = get_model(model_id)
    audio = np.random.default_rng(0).normal(0, .02, 32000).astype(np.float32)
    if model.engine == "sherpa-onnx":
        from .embedding import SpeakerEmbedder
        embedding = SpeakerEmbedder(path, num_threads=1).compute(audio)
        if not np.all(np.isfinite(embedding)):
            raise RuntimeError("Speaker model returned non-finite embeddings.")
    elif model.engine == "faster-whisper":
        from faster_whisper import WhisperModel
        if device == "cuda":
            prepare_cuda_runtime()
        engine = WhisperModel(str(path), device=device, compute_type=compute_type or model.inference_defaults.compute_type,
                              local_files_only=True, cpu_threads=1)
        segments, _info = engine.transcribe(audio, language="en", beam_size=1, vad_filter=False)
        list(segments)
    else:
        if device != "cpu":
            raise ValueError("CUDA readiness is implemented for STT only.")
        import torch
        load_community(path)({"waveform": torch.from_numpy(audio).unsqueeze(0), "sample_rate": 16000})


def main() -> None:
    import sys
    device = sys.argv[3] if len(sys.argv) > 3 else "cpu"
    precision = sys.argv[4] if len(sys.argv) > 4 else None
    probe(sys.argv[1], Path(sys.argv[2]), device=device, compute_type=precision)
    print(f"{device.upper()} model-load and inference smoke passed.")


if __name__ == "__main__":
    main()
