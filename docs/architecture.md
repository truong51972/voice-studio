# Portable editor architecture

Voice Studio remains a PySide6 desktop application. One sequential source track
feeds one QMediaPlayer; AI annotations are not additional playback or mixing tracks.
There is no video rendering, effects pipeline or WebApp migration in this refactor.

## Responsibilities

- `workspace.py`: application-colocated `.projects/` root and actionable write checks.
  Frozen builds use `sys.executable`'s parent; model/runtime resources keep their
  separate existing roots. No project data falls back to the user profile or cwd.
- `projects.py`: v2 JSON manifest, backed-up v1 migration, stable media/clip IDs,
  external fingerprints, immutable analysis files, review revisions, speaker
  aliases/mappings, reference provenance and ordered exports. The historical
  `ProjectItem` API represents persisted media assets; existing domain contracts
  remain available to older callers.
- `domain/timeline.py`: source bounds and the one `map_time` conversion used by
  timeline projection, media seeking, range selection and ordered exports.
- `domain/speakers.py`: project speakers, references, analysis records and overlap
  validation. These modules have no Qt/model imports.
- `ui/session.py`: one application-owned, serialized project task queue; source
  validation/import, durable job states, cancellation, cache activation and result
  routing. Switching projects cancels/reaps the old queue before replacing it.
- `task_runtime.py`: spawn-isolated processes, small path/settings requests and
  disk artifacts. Cancellation terminates the process tree, then removes only the
  job's staging folder. Project results and user data are retained.
- `editor_tasks.py`: worker-side media probing/hashing, streamed waveform peaks,
  region embeddings, bounded-PCM Locator, conservative merge proposals and
  STT/diarization/local-summary dispatch. No model loads on the GUI thread.
- `ui/playback.py`: sequential playback, source loading/seeking, trim boundaries,
  interval preview and source/project clock conversion. Repeated clips do not
  advance twice on an old EndOfMedia event.
- `ui/editor_layout.py`: resizable source library/preview/inspector/timeline and
  view preferences. `ui/main_window.py` connects user actions and projects results.
- `ui/panels/reference.py`, `speakers.py`: source intervals and Auto/Manual/merge
  workflows; no microphone or reference-file enrollment.
- `ui/widgets/timeline.py`: source boundaries, cached peaks, original speaker
  overlaps, transcript/match annotations, range selection, zoom/pan and vertical
  speaker-track scrolling. It never decodes source PCM.

## Time, identity and edits

Persisted inference times always remain relative to their original media.
`TimelineClip` stores `media_id`, `source_in` and optional `source_out` (full source
when null). Timeline starts are derived from clip order. Unknown source durations
must be probed first. A shared boundary selects the next clip; the final endpoint
is seekable. An explicit reference preview may reach outside a trim, with its
source clock clearly distinguished from project time.

Anonymous cluster names are local to an individual analysis of one source.
`cluster_mappings[analysis_id][cluster_id]` points to a stable project speaker;
the analysis record provides the media ID and model/settings provenance. Another
file's “Speaker 1” creates a separate speaker. Similar embeddings only create
proposals; confirmed merges persist aliases and update mappings/references in one
atomic manifest commit. Historical reviewed IDs resolve through aliases on load,
avoiding partial project-wide review rewrites. Split applies to a chosen source
cluster. Names/colors are editable; raw diarization remains unchanged.

Original overlap-aware turns and compatible exclusive turns are both stored.
Only exclusive/conservative turns propose transcript assignments; existing user
speaker corrections are preserved. `TranscriptDocument.raw` and immutable analysis
files hold model hypotheses; edited entries/history are separate review files.
Raw AI inspection and JSON export retain both views. No similarity is presented
as identity verification or a calibrated probability.

## Memory, cache and execution

`media.stream_audio` is shared by STT, existing audio adapters and interval/window
workers. It uses input seeking and output duration for bounded source ranges,
finite mono PCM chunks and reliable decoder cleanup. The editor's Locator keeps
only a rolling PCM window plus scalar scores; multiple references share each
window embedding. Legacy array-based service APIs remain available for callers,
but are not used by editor matching. Upstream pyannote/Torch model memory still
requires real long-recording QA; synthetic streaming tests do not certify it.

Waveforms are built once in a worker as 100ms peaks and reused by content hash.
Embeddings use source fingerprint, interval and verified model SHA. Model file
revisions/settings and reference/mapping revisions enter applicable analysis cache
keys. Reorder/trim does not invalidate raw source inference. Cached activation
rehashes source/reference bytes in a worker, including same-size/mtime edits.
Summary inputs are cached review-snapshot files, not large manifest or IPC values.

All project artifacts/staging stay under the project folder. Job states survive
reopen, with active jobs recovered as interrupted; retry uses the same normal task
controls. `TaskManager`/legacy standalone panel APIs remain for compatibility, but
the actual editor injects one `ProjectSession` and never creates competing panel
managers. Optional models are installed explicitly, not downloaded by analysis.

## Verification

Run `QT_QPA_PLATFORM=offscreen uv run poe test` and `uv run poe check`.
Deterministic regressions cover real generated AAC/FFmpeg streams, source-based
mapping, portable permissions/migration, speaker persistence, streaming windows,
shared queue cancellation, cache fingerprints, review/export and Qt editor flows.
See [implementation/QA evidence](project_workspace_refactor.md) for unrun native
Windows, real-model and long-recording release gates.

Before committing a replacement STT/diarization result, the session asks the UI to
commit its active inline edit and save it against its captured analysis key.
Modal correction dialogs defer view replacement. A late result therefore cannot
write an older document under a newer analysis/revision; unrelated task completions
do not rebuild an active transcript editor. A save failure pauses playback and
blocks project switching/exit, retaining edits for recovery instead of claiming
success. Confirmed speaker choices use stable IDs, including duplicate names.
