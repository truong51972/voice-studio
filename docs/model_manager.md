# Model management — Voice Studio

The Python/runtime installation is independent of model assets. On supported Windows/Linux x64, one `uv sync --locked` provides all production feature runtimes. No models are downloaded on application startup. Users manage assets within **Settings → Models**, not the CLI.

## Model Catalog

The versioned, validated JSON files under `configs/models/` are the single source for model IDs, supported backend, source/revision, license notes, required assets, and inference defaults. `model_catalog.py` enforces safe model asset paths and a known engine allowlist; inference adapters stay in Python. All seven existing model definitions are included.

## Lifecycle and portability

By default model assets are in `.models/`, model preferences in `.settings/models.json`, and projects in `.projects/`, all beside the application executable (or repository root in source builds). User folders are excluded from release ZIPs. Installing updates must not erase them.

The Model Manager supports explicit **Install / Repair**, **Import local folder**, **Discover legacy**, **Verify integrity**, **Test readiness**, **Use as default**, and **Remove / unlink**. Storage can be changed with an explicit path. External/legacy imports are linked without copying; unlink never deletes external weights. Download jobs expose progress, cancellation, retry/resume, and atomic promotion. The app refuses to mutate files for models locked by active inference jobs.

The left-side model tree presents every model with a scannable availability state; the right-hand pane provides details and actions. Statuses distinguish incomplete installs, locally verified assets, CPU-ready models and device-specific CUDA-ready STT models. A manifest records an immutable revision and locally computed hashes, which are integrity checks rather than publisher signatures. Quick GUI status checks do not repeatedly hash multi-GB weights. The explicit **Test CPU** and (STT only) **Test CUDA** actions run separate, isolated offline inference probes. CUDA readiness is stored per model and precision (FP16 or INT8+FP16); a failed CUDA probe never invalidates an already verified CPU profile.

## Community-1

Community-1 is subject to upstream gated access terms. Download it only after accepting the applicable upstream conditions; then use **Import local folder**. The app validates local assets/configuration but never bypasses gating or automatically downloads Community-1 on startup. Run **Test readiness** before analysis.

## Supported/tested boundary

The CI matrix covers Windows/Linux x64 on Python 3.12, native import checks, and model-free regression. Native Windows TorchCodec/FFmpeg shared library packaging and clean-machine playback/model smoke still require release QA. CUDA runtime uses the pinned CUDA 12.8 Torch/torchaudio wheels on Windows/Linux, with CTranslate2 requiring compatible cuBLAS and cuDNN 9 libraries. Installing the wheels is not proof of hardware readiness; run Test CUDA with installed weights on the actual NVIDIA machine. A GPU-ready model may still fail later due to driver/library changes or VRAM pressure. Auto device mode uses GPU only after that probe; otherwise it chooses CPU. See [runtime](inference_runtime.md), [Windows release](windows_release.md) and [QA](quality.md).
