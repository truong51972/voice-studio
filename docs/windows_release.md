# Windows release candidate / diagnostics (#10)

## One-click developer build

Run \`one-click.bat\` from a **Windows PowerShell/CMD machine** with \`uv\`.
The script installs the optional STT CPU runtime, fetches SHA-256 verified
Locator models, packages the PySide6 application as \`dist/voice-studio/\`,
runs the packaged Qt/FFmpeg/speaker runtime smoke and emits a Windows ZIP +
SHA256 checksum.

The same workflow can be triggered manually via **GitHub Actions →
Manual Windows release candidate → Run workflow**. The CI workflow is
opt-in, because network/model downloads and native binary packaging are
expensive. Artifacts are *release candidates*, not automatically approved
production releases.

The baseline Locator model files are bundled (roughly 96 MiB); STT
models are **not** bundled or downloaded until a user selects Install
in the Model Manager. Windows STT builds use \`--with-stt\` to bundle
Python/CTranslate2 runtime libraries; pyannote diarization is an explicit optional runtime build (see below),
not included in the default one-click/STT package.

Run \`voice-studio.exe --smoke-test\` on a real machine or the packaged
candidate workflow; use \`voice-studio.exe --diagnostics\` from a terminal
for model/runtime preflight. If the packaged process is windowed,
console diagnostics may not display; run \`uv run python -m
voice_studio.diagnostics\` on a Python-enabled dev environment.

### Manual release sign-off (not yet achieved by CI)

Projects use `.projects/` beside `voice-studio.exe`, independently of `_internal/`
and the launch working directory. Test actual onedir behavior and a read-only
install; no AppData fallback is permitted. Back up/move `.projects/` before
rebuilding an existing distribution (the build refuses to overwrite it), and
restore it beside a freshly extracted executable when upgrading. Keep original
external media or relink their new locations. Release ZIPs exclude `.projects/`.
See [portable project backup/recovery](projects.md).

- Verify actual audio/video playback, sequential seek, source-range references and
  still-responsive UI after >60 minutes.
- Install Whisper Small through Model Manager, transcribe a consented
  Vietnamese clip on CPU and confirm timestamps/export.
- Test missing model/network failure and recover after cancellation.
- Test CTranslate2 optional CUDA path only when GPU/native DLLs supported;
  publish CPU-only status otherwise.
- Confirm model terms and media consent, verify ZIP SHA256 checksum.
- Test unpack/launch outside developer machine with no Python installation.

Linux/WSL PyInstaller builds create Linux binaries, **not Windows EXEs**.
No cross-compilation claim. ZIP timestamps/file ordering are normalized,
but binary byte-for-byte reproducibility also depends on frozen DLL/wheel
versions. Keep release candidate unsigned until real Windows QA.

### Explicit Community-1 runtime build

The default one-click/STT package does not bundle optional pyannote/Torch. For an
Auto Detect-capable native candidate, explicitly install and collect that runtime:

```powershell
uv sync --dev --extra stt --extra diarization
uv run python scripts/build.py --with-stt --with-diarization
```

This includes runtime packages, not Community-1 model weights or tokens. Obtain a
complete local Community-1 folder separately under its upstream terms and choose
it in Speakers. Verify Torch/audio codec DLL compatibility and real inference on
the candidate; a successful build or import smoke is not model/playback acceptance.
The build fails before packaging if requested runtime packages are unavailable.
