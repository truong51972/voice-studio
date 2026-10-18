# Windows release candidate and native QA

## Default installation

Run `one-click.bat` in a Windows x64 checkout with `uv`, or build manually:

```powershell
uv sync --locked
uv run python -m voice_studio.diagnostics --check-runtimes
uv run python scripts/build.py
uv run python scripts/release_zip.py --platform windows
```

All supported production Python runtimes (PySide6, sherpa-onnx, faster-whisper/CTranslate2, pyannote/Torch, torchaudio and TorchCodec) are installed by **one** `uv sync --locked`, without feature extras. The `dev` group supplies build tools. The build uses PyInstaller onedir and includes versioned JSON model catalogs, the Qt app and native runtime packages. A Linux/WSL build makes a Linux executable, **not** a Windows .exe.

**Models are user-owned assets, not runtime dependencies.** The executable can launch without model weights. Use **Settings → Models** to explicitly install/import, verify and test readiness. Community-1 requires obtaining a complete local model folder under upstream gated-access terms. Neither installation nor release build bypasses these terms.

## Portable data and upgrade safety

```text
VoiceStudio/
  voice-studio.exe
  _internal/             # immutable packaged libraries/catalog
  .projects/             # projects, reviews, history
  .models/               # user-managed model weights
  .settings/             # model/user defaults
```

Release ZIPs exclude `.projects/`, `.models/` and `.settings/`. The build script refuses to overwrite an onedir distribution containing portable user data. For upgrades, close Voice Studio, back up the three user folders and original external media, extract the new application to another writable directory, then restore/verify data before discarding the previous version. Moving the executable alone does not relocate external recordings or linked legacy weights; use Relink / Import.

## Automated gates

`scripts/build.py` checks the bundled catalogs, expected executable/resources and a packaged `--smoke-test`. The packaged smoke imports all mandatory production backends and verifies the FFmpeg executable path without requiring model weights. Dependency import checks **do not** establish real-model inference, native audio/video playback or CUDA compatibility.

The desktop CI matrix covers Python 3.12 on Windows x64 and Linux x64 with `uv sync --locked`, runtime import checks and Qt offscreen tests. These are tests for the relevant commit, not a blanket release sign-off. See GitHub Actions for live results.

## Required manual Windows release acceptance

- Clean-machine extraction launches with no developer Python or uv installation.
- Install and **Test readiness** for a consented Whisper Small model; transcribe Vietnamese and English audio, inspect timestamps, edit and export TXT/SRT/Markdown/JSON.
- Import Community-1 after upstream access approval, verify required local files and run actual CPU diarization; confirm original overlap and exclusive turns remain distinct, and human transcript corrections survive re-analysis.
- Test CAM++ / ERes2NetV2 on real CPU, manual source ranges, multi-source timeline/seek, model changes, cancellation and storage relocation.
- Verify native FFmpeg/TorchCodec libraries when used by the chosen backend, Qt Multimedia playback, microphone operation and long (>60 min) project responsiveness.
- Confirm no model downloads at startup, missing/corrupt model recovery, interrupted download and retry, model in-use protection, restart and preservation of portable data.
- Publish unsupported GPU/CUDA conditions explicitly; no GPU guarantee without real driver/DLL/model probe.
- Review release ZIP SHA-256 and upstream model licenses. Do not call candidate builds fully released until manual acceptance is completed.

See [runtime constraints](inference_runtime.md), [model management](model_manager.md), and [quality gates](quality.md).
