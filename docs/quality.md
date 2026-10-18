# Quality & release acceptance checklist (#12)

## Tracking and ownership

The **release acceptance source of truth** is [Epic #1](https://github.com/truong51972/voice-studio/issues/1). It remains open until representative real recordings, native Windows/Linux desktop sessions, installed models, optional CUDA and the release artifact are evidenced. Keep those results there rather than leaving completed implementation tickets open indefinitely.

| Tracker | Disposition | Release implication |
| --- | --- | --- |
| [#25 — WebApp migration](https://github.com/truong51972/voice-studio/issues/25) | Closed as **not planned**; PySide6 desktop remains the target. | Does **not** waive inherited QA from superseded #24. |
| [#26](https://github.com/truong51972/voice-studio/issues/26) / [PR #27](https://github.com/truong51972/voice-studio/pull/27) | Implementation closed/merged. | Native packaging, real multi-source playback and speaker validation remain pending. |
| [#28](https://github.com/truong51972/voice-studio/issues/28) / [PR #29](https://github.com/truong51972/voice-studio/pull/29) | Dependency, JSON model service and desktop UX implementation merged. | Real packaging/model validation remains pending under #1. |
| [PR #30](https://github.com/truong51972/voice-studio/pull/30) | Model Manager and CUDA-device support merged. | CUDA/CPU probes on actual supported hardware remain pending. |
| [#31](https://github.com/truong51972/voice-studio/issues/31) / [PR #32](https://github.com/truong51972/voice-studio/pull/32) | Progress, WebVTT/SRT, subtitles and timeline interaction merged; issue closed. | Native video subtitle preview and real long-media smoke remain pending. |

Closing a delivered implementation issue never constitutes a passing release gate. Record OS/hardware, Python and native library versions, exact model ID/revision, consented fixture and duration, CPU/CUDA mode, test command, observed output, and remaining failures in the #1 sign-off before calling a release production-ready.

## Deterministic CI

\`uv run poe check && uv run poe test\` runs unit, model-registry,
subprocess, long-chunk-offset (>60 minutes with synthetic audio),
transcript/project persistence and Qt offscreen structure tests. Tests
never download speech models and never claim STT accuracy from synthetic
waveforms. Native Qt Multimedia playback/mic remain hardware smoke tests.

## Consented dataset and manual benchmark

Create a private JSON fixture manifest of redistributable/consented
recordings (do not commit private audio or transcripts):

\`\`\`json
[
  {"source": "/absolute/path/vietnamese.m4a", "reference": "Nội dung nghe được"},
  {"source": "/absolute/path/vietnamese-english.m4a", "reference": "Meeting bắt đầu"},
  {"source": "/absolute/path/noisy.m4a", "reference": "Lời nói thực tế"}
]
\`\`\`

Run after \`uv sync --locked\` and installing a model:

\`\`\`bash
uv run python -m voice_studio.quality \
  --fixtures /path/to/fixtures.json --model whisper-small \
  --language vi --output /path/to/bench-results.json
\`\`\`

Measure WER/CER per consented file and overall; RTF elapsed/duration,
OS/CPU metadata and process maximum RSS (only on platforms supporting
\`resource\`). WER uses whitespace-separated Vietnamese syllables;
CER retains Vietnamese tones. Peak VRAM is \`null\` until a verified
GPU probe exists. These are *measured fields*, not targets or fabricated
benchmark numbers.

For a release run at least Vietnamese, code-mixed Vietnamese/English,
noise, silence, 2-speaker and video-audio cases, plus >60 minute media
where timestamps after the first hour are compared with actual audio.
Keep model revision, options, backend/native library versions, CPU/GPU
and license in the manually signed report.

## Sign-off before release

- [ ] Real Windows x64 clean install opens, plays video, seeks and records.
- [ ] CPU STT and Locator real-model smoke with opt-in downloaded assets.
- [ ] Test long-file chunk offsets, restart/retry and correct transcript export.
- [ ] Cancellation and crash simulation with no leftover subprocess.
- [ ] Check RAM/VRAM/RTF, compare model choices fairly on the *same* audio.
- [ ] Explicit status if CUDA DLL/driver cannot run; CPU remains supported.
- [ ] Review legal use of upstream model artifacts and recording consent.
- [ ] Packaged installer/zip integrity, license and end-user quick start.

**No numeric accuracy guarantee until representative real measurements exist.**
