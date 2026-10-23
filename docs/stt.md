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

After processing, open the **STT** inspector and use **Export transcript…** next to the reviewed result. Choose current source, selected source range or clip-ordered whole project. The default is **WebVTT (.vtt)**, with SRT, TXT, Markdown and JSON available. You can also **Import .vtt/.srt…** to correct an existing transcript. Project `reviews/*.vtt` files are editable subtitle tracks (legacy JSON-only projects upgrade when saved); JSON remains for raw inference/metadata. The File menu has the same export and import actions. **View → Show subtitles** toggles time-aligned soft subtitles in the media preview; no burned-in video is created.

Current scope: offline bounded-chunk STT with project persistence and review/export.

### Interrupted jobs and timestamp recovery

In a project, STT saves a resumable JSON checkpoint after each **completed** audio chunk under `cache/stt-checkpoints/`. The checkpoint key includes the original source fingerprint and all model/inference options, including the model revision. Re-running Transcribe with the same source/model/options skips fully checkpointed chunks and appends the remaining cues; a changed source, model, or option starts a separate job. Successful project analysis removes its checkpoint **after** the finalized result is saved. Failed/cancelled jobs retain the checkpoint and can show the partial cues for current-source export/review; partial cues are *not* a completed project analysis. Do not edit checkpoint JSON manually.

Whisper sometimes reports estimated segment/word timestamps outside a bounded chunk, or non-finite/reversed ranges. Voice Studio now skips malformed/out-of-window cues, clips valid overhanging cues to the actual chunk, and records bounded timestamp warnings in the raw result instead of failing the whole file. This can drop a malformed cue's text; review the transcript/subtitles after a warning. No automatic cross-chunk correction or overlap stitching is currently performed.
GPU support is enabled behind a device-specific native inference probe; actual hardware and packaged Windows acceptance is still pending. Current real-model
accuracy in Vietnamese/English is *unmeasured* until #12 benchmarks
and smoke tests run.
