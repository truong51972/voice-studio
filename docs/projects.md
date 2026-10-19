# Portable projects

On launch, Home automatically discovers the direct child `.projects/*/project.json`
manifests and lists projects by their **name**. Search, double-click or select
**Open project**; no UUID folder selection is necessary. Home reads manifests
without loading models, inspecting external media, migrating or modifying projects.
Use **New project**, give the project a name, and **Import media** to select
multiple recordings. **File → Projects / Home** returns to the list after saved
edits and finished jobs. **File → Recent projects** shows names, not UUIDs.
Home supports Rename and explicit Delete (saved analyses/reviews are removed,
original linked recordings are never deleted). Back up a project before deleting.
The Sources list displays ordered timeline **clips**, not the fixed import
order. Drag a row to reorder or use Edit → Move clip earlier/later; playback and
combined exports follow the persisted clip order. Whole-project STT queues
unique media in first-appearance timeline order, without repeated inference for
a media referenced by multiple clips. Reordering never changes source timestamps
or invalidates cached STT/review revisions.
The project editor uses one sequential source track/player, with source boundaries,
basic trim/move controls, waveform peaks and speaker/STT annotations. Auto Detect
is the default Speakers workflow; see [QA evidence](project_workspace_refactor.md).

## Storage and backups

Projects live in `.projects/<project-id>/` immediately alongside the application:

- Source / `uv run`: `<repository-root>/.projects/`, independent of cwd.
- PyInstaller onedir: `<directory-containing-voice-studio.exe>/.projects/`,
  never `_internal/`, `_MEIPASS`, AppData or the home directory.

The app checks actual write access to both the app folder and `.projects/` before
creating a project. A read-only installation fails with guidance to extract/move
to a writable location such as `D:\VoiceStudio\`; there is no fallback. A normal
Program Files installation is unsuitable without explicit write permission.
Runtime and model caches are separate and are not moved by this change.

Each project contains `project.json`, immutable per-analysis files in `results/`,
revisioned transcript documents in `reviews/`, and waveform/embedding/job caches
in `cache/`. Hashing, probing and inference run in a shared worker queue. Media remain **external absolute
path references**, with SHA-256 fingerprints; no multi-GB files are copied.
Moving just the app folder preserves metadata/results but does **not** move the
original media. Use **Relink** after moving media. Identical content retains the
media ID, clips, cached inference and review; changed content clears the current
cache key and trims, invalidates reference regions, probes new duration/type and
requires a new analysis. Old result files
remain available on disk. Relinking is blocked during batch processing.

Before upgrading, back up `.projects/`, `.models/`, `.settings/` and the separately stored
media. Extract the new version into a new folder, then copy `.projects/` beside
the new executable. Do not replace/delete the old portable folder until the new
copy opens successfully. Release ZIPs exclude user `.projects/` data, and the
build script refuses to overwrite a distribution containing `.projects/`, `.models/` or `.settings/`.
There is no project cleanup on exit or automatic uninstaller. Delete from
Home requires confirmation; alternatively, with the app closed, back up as
needed and remove its portable project folder. External linked media remain
untouched. A project with an unreadable manifest is displayed for recovery
rather than silently discarded from Home.

## Manifest migration and timeline contracts

Version 2 stores stable project/media/clip/speaker/reference/analysis IDs, name,
settings, ordered clips, source-cluster mappings, merge aliases and proposal states.
Large inference outputs and summary review snapshots remain outside the manifest. On first opening v1, the app writes the original manifest bytes
to `project.v1.backup.json` **before** atomically replacing `project.json`. It
preserves media IDs, cache keys, results and reviews. Unsupported versions fail
without modifying the manifest. An interrupted migration can be retried; its
backup is never overwritten. To restore a legacy project from outside the portable
workspace, copy its **entire** folder into `.projects/` before opening it.

The Qt-independent `TimelineMap` derives project starts from clip order and uses
one `map_time` conversion for both directions. Clip ranges are source-relative;
`source_out: null` means the full source once its duration is known. Unknown
durations must be probed before mapping. A shared project boundary belongs to
the following clip; the final end is seekable. Reorder/trim APIs do not modify
raw inference timestamps or invalidate unchanged source/model settings.
Combined Markdown/TXT exports follow clip order, include explicit file/range
boundaries and retain source-relative timestamps. All selected exports clip
segment timestamps and include boundary text only for fully contained timed words.
Without usable word timings (also after text edits), partial segment text is
omitted; entire reviewed segments inside the range retain their text. Empty
omissions do not create lines or subtitle cues. Export status and Help explain
this policy; full-source exports retain complete text.
Combined SRT uses project timestamps and names each source in its cues. Combined
JSON is a **selected timeline export**, not a project archive: it retains explicit
clip/media IDs, fingerprints, source ranges/project starts, source links and only
the selected reviewed entries. Segment/word times are source-relative; clip
`timeline_start` is project-relative. Raw transcripts, history and whole-source
metadata are excluded. Boundary segments include only fully contained timestamped
words; without word timings their text is omitted, with `text_requires_review`
set. Separate source range exports use the same policy in every format. Full-source JSON
still includes raw/reviewed snapshots; back up `.projects` for a full archive.
The GUI shares
this time mapping for playback, tracks, reference selection and export.

Manifest/results/reviews use unique temporary files plus atomic replacement.
Running jobs recover as interrupted on reopen, while missing/changed media require
relinking. Transcript edits remain separate from raw model hypotheses. No database,
cloud upload or user account is required.

Auto/Manual speakers persist across timeline edits. Confirmed project merges
commit aliases/mappings/references in one manifest write; historical transcript
IDs resolve through aliases instead of partially rewriting all review files.
Anonymous cluster numbers from separate files are never treated as identities.
Splitting a source cluster recalculates affected automatic transcript labels from
the union of overlapping turns per mapped speaker. Assignment requires at least
50% of the segment and strictly more than 1.25 times the next speaker's coverage.
Ties or low coverage clear the automatic label and display **Review speaker**,
persisted across reopen. Explicit human assignments (including clearing a label)
and older labels without provenance are preserved. Text corrections are retained.
Automatic assignments record their diarization analysis ID. New diarization
results refresh automatic labels against the latest exclusive mapped turns,
clearing/flagging ambiguous or uncovered spans while retaining human assignments,
explicit clears and text edits. Reusing an archived STT result also refreshes its
automatic labels. Review flags from a split persist for the same analysis and may
be reassessed when another analysis completes; raw inference files never change.

Task records retain failed/cancelled/interrupted states. Switching projects stops
and reaps old jobs first; reopening validates source fingerprints asynchronously.
Use task controls again to retry, **Retry selected reference** for a failed region,
or **Import media** after an interrupted import. No partial source list is committed
if one file in a multi-import fails. Cached inference is reactivated only after
worker-side content verification, including same-size/mtime file edits.
