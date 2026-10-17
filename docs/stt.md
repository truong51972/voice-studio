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

STT jobs show a compact progress strip near the preview: source filename, selected model, actual CPU/CUDA device, processing stage, **completed audio duration / source duration**, elapsed runtime and ETA when enough completed chunks establish throughput. Model loading and the first chunk remain indeterminate rather than jumping to a fabricated percentage. Whole-project transcription shows **Source N/M**; that percent is for the current source only, not the entire project. Cancel stops the subprocess while previously saved transcript reviews remain available.

After processing, open the **STT** inspector and use **Export transcript…** next to the reviewed result. Choose current source, selected source range or clip-ordered whole project. The File menu has the same export commands. TXT, Markdown, SRT and JSON preserve reviewed edits. **View → Show subtitles** toggles time-aligned soft subtitles in the media preview; no burned-in video is created.

Current scope: offline bounded-chunk STT with project persistence and review/export.
GPU support is enabled behind a device-specific native inference probe; actual hardware and packaged Windows acceptance is still pending. Current real-model
accuracy in Vietnamese/English is *unmeasured* until #12 benchmarks
and smoke tests run.
