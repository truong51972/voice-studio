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


def probe(model_id: str, path: Path) -> None:
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
        engine = WhisperModel(str(path), device="cpu", compute_type=model.inference_defaults.compute_type,
                              local_files_only=True, cpu_threads=1)
        segments, _info = engine.transcribe(audio, language="en", beam_size=1, vad_filter=False)
        list(segments)
    else:
        import torch
        load_community(path)({"waveform": torch.from_numpy(audio).unsqueeze(0), "sample_rate": 16000})


def main() -> None:
    import sys
    probe(sys.argv[1], Path(sys.argv[2]))
    print("CPU model-load and inference smoke passed.")


if __name__ == "__main__":
    main()
