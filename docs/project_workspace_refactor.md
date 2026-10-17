# Issue #26 implementation and QA

[Issue #26](https://github.com/truong51972/voice-studio/issues/26) is delivered in
**one implementation PR**, including its earlier foundation commit. Keep that PR
in draft until integrated native/model acceptance passes; `Closes #26` must only
close the issue when the approved PR is merged. WebApp migration #25 stays deferred.

## Implemented

- Project-first PySide6 launch, portable New/Open/Recent, multi-select media import,
  save, external source library and async probe/fingerprint/relink.
- `.projects/` beside repo/executable independently of cwd/_internal; actual write
  checks, no profile fallback, v1 backup/migration, atomic writes, build protection
  and exclusion of private projects from release ZIPs.
- V2 media/clips/settings/speakers/reference regions/analysis records and review
  revisions. Immutable raw files live outside the manifest. Failed/cancelled and
  interrupted job states persist; imports commit atomically.
- One player and shared source/project time mapping, ordered playback/seek/trim,
  explicit move controls, distinguishable clocks, range preview, zoom/pan and
  source/speaker/STT/match tracks with cached streamed waveform peaks.
- Auto-first optional local Community-1; original overlaps and separate exclusive
  turns, stable per-analysis/source cluster mappings and preserved manual edits.
- Source-interval references (no file/microphone enrollment), multiple references,
  bounds/short/silence/known-overlap validation, bounded FFmpeg decoding and
  fingerprint/range/model-revision embedding cache. No pyannote requirement for
  manual matching. Unknown overlap requires listening, not invented certainty.
- Bounded-PCM CAM++/ERes2NetV2 matching, clean representative/reference comparison,
  ambiguous proposals, explicit merge/split confirmation and persistent aliases.
- One serialized project queue, cancellation/process cleanup and project-switch
  isolation. Source inference is reused across timeline edits after asynchronous
  fingerprint verification. Same-size/mtime source edits are detected.
- Preserved STT/language/VAD/word controls and transcript search/edit/split/merge,
  source selection exports and ordered TXT/Markdown/SRT/JSON project exports.
  Local Ollama supports selected-source or ordered project review snapshots with
  source-specific citation anchors; raw transcripts are never replaced.
- Default Windows one-click/workflow builds include STT and `--with-diarization`
  runtimes, checked by mandatory packaged pyannote/Torch import smoke. Community-1
  models are installed separately; no automatic model/token/cloud dependency is
  introduced. Real native runtime/inference acceptance remains open.

## Deterministic evidence

`QT_QPA_PLATFORM=offscreen uv run poe test`, `uv run poe check`, and
`git diff --check` are the local/CI checks. New tests cover real generated AAC/M4A
imports and bounded source extraction, WAV/FLAC regression, actual stream-based
media kind, portable roots/permissions, migration/write failures, speaker mappings,
confirmed aliases/splits, references, cache invalidation, exports, task cancellation,
project switches and Qt import/trim/reorder/save/reopen flows.

PR review regressions also cover all selected export formats excluding out-of-range
speech; JSON without excluded raw text, metadata or word timestamps; overlap-based
cluster splits with persisted review flags and preserved human corrections;
diarization v1 → v2 → reopen with automatic analysis provenance, ambiguity, human
overrides and cached transcript reactivation; and default Windows runtime/build-smoke
policy. The local model-free suite passes **178 tests**. Packaging tests simulate
build outputs and smoke failure; they do not replace a real Windows build/run.

The 61-minute Locator/STT checks generate synthetic PCM chunks and assert bounded
windows/timestamps; they do **not** benchmark a real 61-minute recording or model.
The frozen-root test simulates PyInstaller; it does **not** certify Windows onedir.

Linux Qt offscreen screenshots use deterministic sine-wave/annotation/transcript
fixtures (no real-model claim):

- [Auto / timeline](qa/issue-26-auto.png)
- [Manual source reference](qa/issue-26-manual.png)

## Integrated acceptance still open

- Real Windows onedir: `.projects/` next to exe, writable/read-only installations,
  app-folder move, native Qt codec/runtime errors, three AAC M4A files, sequential
  audio/video playback and seeking across source/trim boundaries.
- Explicitly installed Community-1 on controlled real multi-speaker/overlap audio,
  plus real CAM++/ERes2NetV2 reference matching and cross-file proposal quality.
- Real >60-minute GUI/model workflow with measured responsiveness, memory,
  cancellation and reopen/retry; optional Torch/codec/CUDA native compatibility.

No Windows, real multi-speaker accuracy or real long-recording success is claimed.
Use the issue's full acceptance checklist on the one PR and attach measured
results before merge; model-free CI cannot sign off these manual gates.
