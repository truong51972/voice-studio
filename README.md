# Voice Studio

A **local-first PySide6 desktop editor** for audio/video analysis, bootstrapped from the working **Voice Locator v0.5.1** native editor with the same media-first UI.

> **Foundation release / v0.1.0:** Known-speaker localization works; **speech-to-text, diarization, transcript editing, batch projects and AI summarization are not implemented yet.** See the [roadmap](https://github.com/truong51972/voice-studio/issues/1).

## Features available now

- Resizable dark/cyan workspace with native audio/video preview, inspector, bottom speaker timeline and shared playhead.
- Import local audio or video, FFmpeg media extraction, seek, scrub, overlay matching speaker regions.
- Register 1–3 known reference speakers (file upload or microphone recording).
- Two local embedding profiles: CAM++ (Fast) and ERes2NetV2 (Accurate); profile threshold, per-speaker matching and segment details.
- Offline/private analysis; no server or cloud upload required.

**Voice matching is not anonymous-speaker diarization or identity verification.** Cosine similarity is not a probability.

## Run locally

Requires Python 3.11–3.12, [uv](https://docs.astral.sh/uv/) and a compatible Qt desktop. Some Linux distributions need multimedia packages.

```bash
uv sync --dev
uv run poe models      # download and verify CAM++ / ERes2NetV2 ONNX models
uv run poe start       # start desktop UI
uv run poe test        # unit tests + Qt offscreen tests
uv run poe check       # compile all Python files
```

Alternative entrypoints: `uv run poe desktop`, `uv run voice-studio`, `uv run python -m voice_studio`.

The speaker ONNX models (approximately 96 MiB total) download only on request, are checked against their SHA-256 and never committed to Git.

## Workflow

1. In **Workspace**, open the target audio or video.
2. Under **Speakers**, add 1–3 known reference recordings.
3. Under **Analysis**, select CAM++/ERes2NetV2 and threshold; select **Analyze**.
4. Inspect matching speaker clips on the timeline, seek by clicking, and review segment details.

The player, overlay, seek/playhead and QSplitter structure intentionally remain equivalent to Voice Locator v0.5.1. The educational page has been replaced with a general Help tab.

## Repo

```text
src/voice_studio/  desktop UI, media, matching, local services
scripts/           model download and development build helper
tests/             audio, similarity, UI, seek, profiles and download regression tests
assets/            new Voice Studio icon
models/            local-only model data
```

## Scope and release caveats

The existing `uv run poe build` PyInstaller helper is carried forward, but **Windows packaging, GPU runtime and native media integration have not yet been signed off**. See [issue #10](https://github.com/truong51972/voice-studio/issues/10). CI covers model-free Linux/Qt offscreen tests only; local smoke tests with downloaded models, real playback and Windows are required.

Next: [#3 UI/domain contracts](https://github.com/truong51972/voice-studio/issues/3) → [#4 registry](https://github.com/truong51972/voice-studio/issues/4) / [#5 cancellable runtime](https://github.com/truong51972/voice-studio/issues/5) → [#6 STT](https://github.com/truong51972/voice-studio/issues/6) → [#7 transcripts](https://github.com/truong51972/voice-studio/issues/7) → [#8 batch](https://github.com/truong51972/voice-studio/issues/8). Test gates: [#12](https://github.com/truong51972/voice-studio/issues/12).

## Provenance

This bootstrap ports the source code from [AI-Voice-Locator-Education](https://github.com/truong51972/AI-Voice-Locator-Education) v0.5.1 on `main` (2026-10-17) without changing the original repository. Algorithm, model hashes, thresholds, timeline and player behavior are retained.
