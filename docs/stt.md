# Offline STT (issue #6)

Install Python runtimes once, then install a selected model using **Settings → Models**:

\`\`\`bash
uv sync --locked
uv run poe start
\`\`\`

Open a local M4A, MP3, WAV, FLAC or video file in the editor. In the
**STT** inspector select a model, language (auto/vi/en), VAD and word
timestamps and device (Auto, NVIDIA CUDA or CPU), then press **Transcribe**. CUDA offers FP16 and INT8+FP16 compute types. Auto selects a verified CUDA profile when available and otherwise uses CPU INT8; explicitly selected CUDA reports a readiness error instead of silently switching to CPU. The installed snapshot is loaded
by path with \`local_files_only=True\`; no media uploads or remote APIs.
Click any transcript segment to seek the **same player** as Locator.

The FFmpeg decoder produces 16-kHz mono float32 in up to 30s chunks,
so it never keeps the full 60–90 minute waveform in memory. Source time
offsets are sample-derived, not guessed from FFmpeg timestamps.
There is **no chunk overlap** in this initial implementation: a word
crossing a boundary may require human correction. Silence is skipped.
CPU inference can take considerable time, especially Large v3. Under **Settings → Models**, install the Whisper model, run **Test CPU** and separately **Test CUDA** if desired. CUDA needs a compatible NVIDIA driver, cuBLAS and cuDNN 9. The CUDA-enabled Torch dependency does not itself guarantee CTranslate2 can load GPU libraries.
The model's VAD and optional word timestamp switches are passed to the
backend, not just rendered as decorative UI.

Current scope: local first pass with segment timestamps, SQLite-free,
Qt process worker and export-ready structured JSON. User correction
and SRT/Markdown export are issue #7; multi-file persistence is #8.
GPU support is enabled behind a device-specific native inference probe; actual hardware and packaged Windows acceptance is still pending. Current real-model
accuracy in Vietnamese/English is *unmeasured* until #12 benchmarks
and smoke tests run.
