# Issue #26 implementation status

[Issue #26](https://github.com/truong51972/voice-studio/issues/26) is one PySide6
refactor delivered in **one implementation PR**, with topical commits and
`Closes #26` in its eventual description. Do not merge/close it until integrated
acceptance passes. WebApp migration #25 stays deferred. No implementation PR has
been created by this initial work.

## Implemented foundation

- Portable root resolution independent of cwd and bundled-resource paths;
  actionable write failures, `.gitignore`, build protection and release exclusion.
- Projects inspector New/Open/Recent controls using portable storage.
- Initial v2 project/media/clip/settings persistence; exact v1 backup before
  migration, atomic writes, legacy cache/review retention and interrupted jobs.
- Qt-independent sequential clip/time mapping, trim/reorder APIs and ordered
  source-bounded report exports. These APIs are not yet the GUI playback clock.
- Shared chunked FFmpeg decoder for STT, Locator audio/video and bounded source
  intervals. Real generated AAC/M4A and WAV/FLAC decoding are regression tested.
- Original overlap-aware diarization and separately mapped exclusive turns;
  transcript assignment consumes exclusive output when present.
- Relinked transcript edits save against the active document, preventing unrelated
  or stale documents from overwriting reviews.

## Remaining in the same implementation PR

1. Make launch project-first; add file/toolbar actions, source library and
   asynchronous import/probing/fingerprints. Wire actual media type/duration to
   the v2 store. Large-file hashing currently still runs synchronously.
2. Wire the sequential project clock to the one player, source/speaker/STT tracks,
   preview, seek, trim/reorder, zoom/pan and distinct source/project readouts.
   Add streaming cached waveform peaks and readable Qt playback errors.
3. Make Auto Detect the default Speakers workflow. Persist project speaker IDs
   and explicit `(media_id, cluster_id)` mappings, raw task results/settings and
   speaker corrections. Cluster labels from separate files must never auto-merge.
4. Replace file/microphone reference enrollment with timeline/typed source ranges,
   interval preview, multi-region provenance and bounded worker decoding. Validate
   silence, short/overlapping speech; cache embeddings by content/region/model
   revision. Keep manual Locator usable without pyannote. The existing Locator
   still collects the full target PCM array; chunked decoding alone does not
   complete the long-recording memory requirement.
5. Add conservative cross-file embedding suggestions and explicit merge/split
   confirmation; persist mappings through reimport/reorder/reopen. Similarity must
   not be presented as identity verification or calibrated confidence.
6. Centralize application task dispatch, persist per-task state/results under each
   project, and wire cancellation/retry/project-switch protection for every panel.
   Existing panels still own independent managers and temporary task folders.
7. Integrate all review/export paths and update final Help/docs for the completed
   Auto-first workflow. Extend v2 metadata with speaker/reference/task records.

## Acceptance evidence still required

Model-free Linux/offscreen tests cover deterministic storage/time/codec behavior;
the frozen-root test simulates packaging and is **not** a real Windows build test.
No Windows native GUI/playback, explicitly installed Community-1 multi-speaker
sample, embedding accuracy, cross-source matching or real >60-minute workflow has
been signed off. Check every acceptance item in the issue on the one PR, attach
actual test evidence, and leave unrun items open.
