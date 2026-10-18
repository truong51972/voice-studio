# Voice Studio

A **local-first PySide6 desktop editor** for audio/video analysis, bootstrapped from the working **Voice Locator v0.5.1** native editor with the same media-first UI.

> **Development preview / v0.1.0:** Portable projects, a multi-source editor, Auto/Manual speakers, STT review and local summaries are implemented in source. Deterministic Linux regressions cover the new workflows; **real-model accuracy, Windows package and native media/model smoke tests are not yet signed off.** See the [Epic and acceptance checklist](https://github.com/truong51972/voice-studio/issues/1).

## Features available now

- Project-first New/Open/Recent with portable `.projects/` storage beside the app.
- Multi-select audio/video import, external source links, fingerprint checks and relinking.
- Resizable dark/cyan source library, one preview/player, **two-tab Transcript / Speakers inspector**, and ordered source/speaker/STT timeline. Less-frequent engineering tools are accessible on demand from the menus.
- **Timeline:** click to seek, drag playhead/ruler to scrub, drag zoomed canvas or middle button to pan, Shift+drag to select an interval, wheel to zoom around the pointer. Active playback auto-follows until you manually navigate; zoom is consistent up to 128×.
- **Fast review:** primary Transcribe action with collapsible Options; transcript export chooses source/selection/project scope on demand; source list summarizes completed STT/speaker matching and elapsed-style durations. Current subtitle cue scrolls into view unless you are manually navigating the transcript.
- Sequential playback/seek, basic trim and move controls, dual source/project clocks, cached waveform peaks, zoom/pan and range selection.
- **Auto Detect Speakers** by default using optional explicitly installed local Community-1; original overlap and separate exclusive turns remain available.
- Optional **manual references from source intervals**: type or drag a range, preview, name/choose a project speaker and embed. Multiple regions per speaker; no reference upload or microphone enrollment.
- CAM++ (Fast) / ERes2NetV2 (Accurate) matching with bounded PCM windows, editable labels/colors, conservative comparison proposals and confirmed merge/split.
- Offline faster-whisper STT (Vietnamese/English/auto), VAD and word timestamps; searchable, editable transcripts and separate raw AI results.
- TXT/SRT/Markdown/JSON exports for a source/selection or ordered combined project, with explicit source boundaries and provenance.
- One serialized project worker queue, cancellation/retry, persistent failed/interrupted state, backed-up v1 migration and atomic saves.
- Optional localhost Ollama **AI draft** summaries of a source or ordered project review snapshot, with source-specific citations; separate FFmpeg denoise utility.

The [portable editor refactor #26](https://github.com/truong51972/voice-studio/issues/26) was delivered through merged [PR #27](https://github.com/truong51972/voice-studio/pull/27). **PySide6 remains the product UI**; the [WebApp migration proposal #25](https://github.com/truong51972/voice-studio/issues/25) was closed as **not planned**. See [implementation and QA evidence](docs/project_workspace_refactor.md). Real Windows packaging, installed-model inference and long-recording acceptance remain **release gates**, tracked in [Epic #1](https://github.com/truong51972/voice-studio/issues/1), not unmerged feature work.

**Voice matching is not anonymous-speaker diarization or identity verification.** Cosine similarity is not a probability.

## Run locally

Requires Python 3.12, [uv](https://docs.astral.sh/uv/) and a compatible Qt desktop. Some Linux distributions need multimedia packages.

```bash
uv sync --locked
uv run poe models      # optional developer prefetch only; Settings → Models is the GUI
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

Model management: [docs/model_manager.md](docs/model_manager.md). **Settings → Models** installs, imports, verifies, repairs and tests readiness; no optional Python extras or CLI model setup for end users. All feature runtimes are installed by a single `uv sync --locked`; weights are downloaded only when requested.

## Workflow

1. **New/Open/Recent Project**, then **Import media** (multiple recordings). Sources populate the library and ordered timeline without being copied.
2. Select a source, play/seek across clip boundaries, move/trim clips, zoom/pan or drag/type a source range. Source and project clocks are separate.
3. Import a complete local Community-1 folder under **Settings → Models** after accepting the upstream gated terms, test readiness, then select **Process → Auto Detect Speakers**. Toolbar scope chooses the current source or whole project.
5. Under **Transcript** (the default right-hand inspector), select an installed model/language and **Transcribe**. Review text/speakers, split/merge and export WebVTT (.vtt), SRT or other formats for the source/selection; whole-project export follows clip order and trims.
6. The right inspector normally shows only **Transcript** and **Speakers**. Open optional **Process → Summarize…** for source-cited localhost Ollama drafts, or **View → Advanced tools** for Analysis, Segments, Project details, or Raw AI results. Settings → Inference defaults exposes the analysis controls. An advanced panel is temporary and can be closed to return to Transcript. **Cancel jobs** stops the shared queue; rerun the task controls or retry a selected reference after fixing an error.
7. **Save** and reopen: clips, source links, speaker mappings/references, raw results, review revisions and interrupted states persist.

Source checkouts use `<repo>/.projects/` independently of cwd; onedir builds use `<exe-directory>/.projects/`. The portable folder must be writable. Back up the entire `.projects/` folder and external media before upgrades/moves: moving only the app does not move the recordings. Portable model assets and preferences default to sibling `.models/` and `.settings/` folders. Linked legacy models stay at their original locations and are never deleted by unlink. See [Projects](docs/projects.md) for backup and migration.

## Repo

Architecture and timebase contracts: [docs/architecture.md](docs/architecture.md).

```text
src/voice_studio/  desktop UI, media, matching, local services
scripts/           model download and development build helper
tests/             audio, similarity, UI, seek, profiles and download regression tests
assets/            new Voice Studio icon
configs/models/    versioned JSON model metadata (packaged with app)
.models/           portable user model assets (not committed)
.settings/         portable preferences (not committed)
```

## Scope and release caveats

The manually triggered Windows release-candidate workflow and `one-click.bat` bundle STT and Auto Detect runtimes by default. Install a complete local Community-1 model separately and choose its folder in Speakers. **Windows packaging, optional CUDA runtime and native media/model tests have not yet been signed off**. CI runs model-free Windows/Linux Qt offscreen tests on Python 3.12; use real recordings and installed models for acceptance. See [Windows release guide](docs/windows_release.md) and [quality gates](docs/quality.md).

Detailed workflows: [STT](docs/stt.md) · [Transcript](docs/transcript.md) · [Projects](docs/projects.md) · [Diarization](docs/diarization.md) · [Optional local AI drafts](docs/enhancements.md).

**Implementation PRs #13–#23, #27, #29, #30 and #32 have been merged into `main`.** [PR #29](https://github.com/truong51972/voice-studio/pull/29) delivered the dependency/model/menu refactor from [#28](https://github.com/truong51972/voice-studio/issues/28), [PR #30](https://github.com/truong51972/voice-studio/pull/30) improved the model manager and CUDA STT, and [PR #32](https://github.com/truong51972/voice-studio/pull/32) completed subtitle/progress/timeline work from [#31](https://github.com/truong51972/voice-studio/issues/31). **Merging implementation is not release sign-off.** See [Epic #1](https://github.com/truong51972/voice-studio/issues/1) and [quality gates](docs/quality.md) for outstanding physical-device and real-audio checks.

## Provenance

This bootstrap ports the source code from [AI-Voice-Locator-Education](https://github.com/truong51972/AI-Voice-Locator-Education) v0.5.1 on `main` (2026-10-17) without changing the original repository. Algorithm, model hashes, thresholds, timeline and player behavior are retained.
