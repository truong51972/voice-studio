# Portable projects

Use **Projects → New**, give the project a name, and **Add media** to select
multiple recordings. **Open project** and **Recent** reopen existing projects.
The current GUI still queues STT per file; the integrated project timeline and
Auto-first Speakers inspector are the next parts of [refactor #26](project_workspace_refactor.md).

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

Each project contains `project.json`, immutable per-run STT files in `results/`
and revisioned transcript documents in `reviews/`. Media remain **external absolute
path references**, with SHA-256 fingerprints; no multi-GB files are copied.
Moving just the app folder preserves metadata/results but does **not** move the
original media. Use **Relink** after moving media. Identical content retains the
media ID, clips, cached inference and review; changed content clears the current
cache key, duration/type and trims, and requires a new analysis. Old result files
remain available on disk. Relinking is blocked during batch processing.

Before upgrading, back up the entire `.projects/` folder and the separately stored
media. Extract the new version into a new folder, then copy `.projects/` beside
the new executable. Do not replace/delete the old portable folder until the new
copy opens successfully. Release ZIPs exclude user `.projects/` data, and the
build script refuses to overwrite a distribution that contains `.projects/`.
There is no project cleanup on exit or automatic uninstaller. To delete a
project, close the app, back up as needed and explicitly remove its project
folder yourself; external media are unaffected.

## Manifest migration and timeline contracts

Version 2 stores the stable project ID, name, settings, media entries and ordered
clips separately. On first opening v1, the app writes the original manifest bytes
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
boundaries and retain source-relative timestamps. They include overlapping
transcript segments with timestamps clipped to the range; partially selected
segments retain their text for human review rather than inventing word cuts.
GUI trim/reorder and shared project playback are still pending.

Manifest/results/reviews use unique temporary files plus atomic replacement.
Running jobs recover as interrupted on reopen, while missing/changed media require
relinking. Transcript edits remain separate from raw model hypotheses. No database,
cloud upload or user account is required.
