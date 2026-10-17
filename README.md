# Voice Studio

A **local-first PySide6 desktop editor** for audio/video analysis, bootstrapped from the working **Voice Locator v0.5.1** native editor with the same media-first UI.

> **Development preview / v0.1.0:** Locator, offline STT, transcript editing, batch projects and optional diarization/local summarization are implemented in source. CI passes; **real-model accuracy, Windows package and native media/microphone smoke tests are not yet signed off.** See the [Epic and acceptance checklist](https://github.com/truong51972/voice-studio/issues/1).

## Features available now

- Resizable dark/cyan workspace with native audio/video preview, inspector, bottom speaker timeline and shared playhead.
- Import local audio or video, FFmpeg media extraction, seek, scrub, overlay matching speaker regions.
- Register 1–3 known reference speakers (file upload or microphone recording).
- Two local embedding profiles: CAM++ (Fast) and ERes2NetV2 (Accurate); profile threshold, per-speaker matching and segment details.
- Offline/private Locator analysis; no cloud upload required.
- Offline **faster-whisper STT** (Vietnamese/English/auto language selection), word timestamps and source-aligned segments.
- Editable, searchable transcripts; split/merge, speaker labels, common-player seek and TXT/SRT/Markdown/JSON exports.
- Multi-file local project queue, per-file cache and reviewed transcripts, combined Markdown/TXT exports.
- Optional local Community-1 diarization, anonymous speaker turns and editable attribution.
- Optional localhost Ollama source-cited **AI draft** summaries and separate FFmpeg audio denoise output.

**Voice matching is not anonymous-speaker diarization or identity verification.** Cosine similarity is not a probability.

## Run locally

Targets Windows x64 and Linux x64 with Python 3.11–3.12, [uv](https://docs.astral.sh/uv/) and a compatible Qt desktop. Some Linux distributions need multimedia packages. See the [runtime verification and platform limits](docs/inference_runtime.md). macOS and other architectures are outside the current runtime matrix.

```bash
uv sync --locked
uv run poe start       # start desktop UI
uv run poe models      # optional developer download of both speaker models
uv run poe test        # unit tests + Qt offscreen tests
uv run poe check       # compile all Python files
```

Alternative entrypoints: `uv run poe desktop`, `uv run voice-studio`, `uv run python -m voice_studio`.

On Linux, the app defaults to the PulseAudio audio backend (also supported by
PipeWire's PulseAudio compatibility server). This avoids a Qt native crash on
systems such as WSLg where PipeWire's `client.conf` is missing. An explicit
`QT_AUDIO_BACKEND` environment variable takes precedence.

The speaker ONNX models (approximately 96 MiB total) download only on request, are checked against their SHA-256 and never committed to Git.

One `uv sync --locked` installs all production Python runtimes, including STT and diarization. Model weights are separate: open **Models** to install speaker/STT assets. Community-1 still uses the existing local-folder workflow. Downloads happen only when explicitly requested. See [model management](docs/model_manager.md).

## Workflow

1. In **Workspace**, open the target audio or video.
2. Under **Speakers**, add 1–3 known reference recordings.
3. Under **Analysis**, select CAM++/ERes2NetV2 and threshold; select **Analyze**.
4. Inspect matching speaker clips on the timeline, seek by clicking, and review segment details.
5. For STT, select the **STT** inspector, choose an installed model/language, then **Transcribe**. Edit segments and export the reviewed result.
6. Use **Projects** for a batch of recordings, **Diarization** for optional anonymous speaker clustering, or **Summary** for explicit localhost Ollama-generated drafts.

The player, overlay, seek/playhead and QSplitter structure intentionally remain equivalent to Voice Locator v0.5.1. The educational page has been replaced with a general Help tab.

## Repo

Architecture and timebase contracts: [docs/architecture.md](docs/architecture.md).

```text
src/voice_studio/  desktop UI, media, matching, local services
configs/models/    versioned, validated model catalog (bundled with the app)
scripts/           model download and development build helper
tests/             audio, similarity, UI, seek, profiles and download regression tests
assets/            new Voice Studio icon
models/            local-only model data
```

## Scope and release caveats

The manually triggered Windows release-candidate workflow and `one-click.bat` are available, but **Windows packaging, optional CUDA runtime and native media/microphone tests have not yet been signed off**. CI is configured for model-free Windows/Linux tests and Qt offscreen checks; use real recordings and installed models for acceptance. See [Windows release guide](docs/windows_release.md) and [quality gates](docs/quality.md).

Detailed workflows: [STT](docs/stt.md) · [Transcript](docs/transcript.md) · [Projects](docs/projects.md) · [Diarization](docs/diarization.md) · [Optional local AI drafts](docs/enhancements.md).

**Implementation PRs #15–#23 have all been merged into `main`.** See [Epic #1](https://github.com/truong51972/voice-studio/issues/1) for remaining real-device, long-recording and model benchmarks.

## Provenance

This bootstrap ports the source code from [AI-Voice-Locator-Education](https://github.com/truong51972/AI-Voice-Locator-Education) v0.5.1 on `main` (2026-10-17) without changing the original repository. Algorithm, model hashes, thresholds, timeline and player behavior are retained.
