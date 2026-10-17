# Voice Studio

A **local-first PySide6 desktop editor** for audio/video analysis, bootstrapped from the working **Voice Locator v0.5.1** native editor with the same media-first UI.

> **Development preview / v0.1.0:** Portable projects, a multi-source editor, Auto/Manual speakers, STT review and local summaries are implemented in source. Deterministic Linux regressions cover the new workflows; **real-model accuracy, Windows package and native media/model smoke tests are not yet signed off.** See the [Epic and acceptance checklist](https://github.com/truong51972/voice-studio/issues/1).

## Features available now

- Project-first New/Open/Recent with portable `.projects/` storage beside the app.
- Multi-select audio/video import, external source links, fingerprint checks and relinking.
- Resizable dark/cyan source library, one preview/player, inspector and ordered source/speaker/STT timeline.
- Sequential playback/seek, basic trim and move controls, dual source/project clocks, cached waveform peaks, zoom/pan and range selection.
- **Auto Detect Speakers** by default using optional explicitly installed local Community-1; original overlap and separate exclusive turns remain available.
- Optional **manual references from source intervals**: type or drag a range, preview, name/choose a project speaker and embed. Multiple regions per speaker; no reference upload or microphone enrollment.
- CAM++ (Fast) / ERes2NetV2 (Accurate) matching with bounded PCM windows, editable labels/colors, conservative comparison proposals and confirmed merge/split.
- Offline faster-whisper STT (Vietnamese/English/auto), VAD and word timestamps; searchable, editable transcripts and separate raw AI results.
- TXT/SRT/Markdown/JSON exports for a source/selection or ordered combined project, with explicit source boundaries and provenance.
- One serialized project worker queue, cancellation/retry, persistent failed/interrupted state, backed-up v1 migration and atomic saves.
- Optional localhost Ollama **AI draft** summaries of a source or ordered project review snapshot, with source-specific citations; separate FFmpeg denoise utility.

The [single-PR issue #26 refactor](https://github.com/truong51972/voice-studio/issues/26) retains PySide6 and leaves WebApp migration #25 deferred. See [implementation and QA evidence](docs/project_workspace_refactor.md); native Windows, real-model and real long-recording acceptance must pass before merge/release.

**Voice matching is not anonymous-speaker diarization or identity verification.** Cosine similarity is not a probability.

## Run locally

Requires Python 3.11–3.12, [uv](https://docs.astral.sh/uv/) and a compatible Qt desktop. Some Linux distributions need multimedia packages.

```bash
uv sync --dev
# Optional STT dependencies: uv sync --dev --extra stt
uv run poe models      # download and verify CAM++ / ERes2NetV2 ONNX models
uv run poe start       # start desktop UI
uv run poe test        # unit tests + Qt offscreen tests
uv run poe check       # compile all Python files
```

Alternative entrypoints: `uv run poe desktop`, `uv run voice-studio`, `uv run python -m voice_studio`.

On Linux, the app defaults to the PulseAudio audio backend (also supported by
PipeWire's PulseAudio compatibility server). This avoids a Qt native crash on
systems such as WSLg where PipeWire's `client.conf` is missing. An explicit
`QT_AUDIO_BACKEND` environment variable takes precedence.

The speaker ONNX models (approximately 96 MiB total) download only on request, are checked against their SHA-256 and never committed to Git.

Model management: [docs/model_manager.md](docs/model_manager.md). Open **Models** to install and verify assets. To run local transcription, install optional dependencies with `uv sync --dev --extra stt`, then install an STT model using the Model Manager. Model downloads happen only when explicitly requested.

## Workflow

1. **New/Open/Recent Project**, then **Import media** (multiple recordings). Sources populate the library and ordered timeline without being copied.
2. Select a source, play/seek across clip boundaries, move/trim clips, zoom/pan or drag/type a source range. Source and project clocks are separate.
3. Under **Speakers → Auto Detect**, choose a complete locally installed Community-1 folder, then **Auto Detect Speakers**. Install its optional runtime with `uv sync --dev --extra diarization`; no token or automatic model download is used. Toolbar scope selects one source or the whole project.
4. Optionally **Add manual reference**: preview a clean source interval, choose/type a speaker label, confirm one voice, and add it. Choose a CAM++/ERes2NetV2 profile in **Analysis**, then **Match references**. Manual matching does not require pyannote. Compare project speakers to review merge proposals.
5. Under **STT**, select an installed model/language and **Transcribe**. Review text/speakers, split/merge and export the source/selection; **Export all** follows project clip order and trims.
6. **Summary** generates explicit source-cited localhost Ollama drafts. **Raw AI** retains immutable inference separately from corrections. **Cancel jobs** stops the shared queue; rerun the task controls or retry a selected reference after fixing an error.
7. **Save** and reopen: clips, source links, speaker mappings/references, raw results, review revisions and interrupted states persist.

Source checkouts use `<repo>/.projects/` independently of cwd; onedir builds use `<exe-directory>/.projects/`. The portable folder must be writable. Back up the entire `.projects/` folder and external media before upgrades/moves: moving only the app does not move the recordings. Runtime/model cache paths remain separate. See [Projects](docs/projects.md) for backup and migration.

## Repo

Architecture and timebase contracts: [docs/architecture.md](docs/architecture.md).

```text
src/voice_studio/  desktop UI, media, matching, local services
scripts/           model download and development build helper
tests/             audio, similarity, UI, seek, profiles and download regression tests
assets/            new Voice Studio icon
models/            local-only model data
```

## Scope and release caveats

The manually triggered Windows release-candidate workflow and `one-click.bat` are available, but **Windows packaging, optional CUDA runtime and native media/microphone tests have not yet been signed off**. CI covers model-free Linux/Qt offscreen tests; use real recordings and installed models for acceptance. See [Windows release guide](docs/windows_release.md) and [quality gates](docs/quality.md).

Detailed workflows: [STT](docs/stt.md) · [Transcript](docs/transcript.md) · [Projects](docs/projects.md) · [Diarization](docs/diarization.md) · [Optional local AI drafts](docs/enhancements.md).

**Implementation PRs #15–#23 have all been merged into `main`.** See [Epic #1](https://github.com/truong51972/voice-studio/issues/1) for remaining real-device, long-recording and model benchmarks.

## Provenance

This bootstrap ports the source code from [AI-Voice-Locator-Education](https://github.com/truong51972/AI-Voice-Locator-Education) v0.5.1 on `main` (2026-10-17) without changing the original repository. Algorithm, model hashes, thresholds, timeline and player behavior are retained.
