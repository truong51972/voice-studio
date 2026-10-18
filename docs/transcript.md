# Transcript review and export

The STT panel supports searching segment text, click-to-seek, text edits,
manual speaker labels, split/merge adjacent segments and reverting all edits.
Raw STT hypotheses remain immutable in \`TranscriptDocument.raw\`; edits
are a separate revisioned view. Any word timestamps belonging to edited
text are cleared because they would otherwise be misleading.

Exports: **WebVTT (.vtt)**, SRT, TXT, Markdown and JSON, with media source provenance, coherent
media-local timestamps and any user corrections. Full-source JSON contains both raw
inference and edited segments. SRT uses valid \`HH:MM:SS,mmm\` timestamps
and sequential cue numbering. Empty text is omitted.

Split places the original text in the first segment and an empty second
segment for manual review, rather than inventing the content of the split.
Merging two differently attributed speakers resets speaker attribution to
unknown. Transcripts in multiple source files remain independent (#8).

In the project editor, automatic speaker IDs resolve to editable project names.
Exclusive diarization refreshes automatic assignments against the latest completed
analysis, including when an archived STT result is reactivated from cache. Each
automatic label records its `speaker_analysis_id`. Uncertain ties or uncovered
spans clear the automatic label and display **Review speaker**; a different
analysis can resolve that warning. Reapplying the same analysis preserves review
warnings from a cluster split. Explicit human assignments/clears, legacy labels
without provenance and text corrections are preserved; raw hypotheses are unchanged.
Confirmed aliases resolve historical IDs.
The standard **WebVTT (.vtt) file** under the project's `reviews/` directory
contains edited subtitle cues and is authoritative for cue text and timing.
The adjacent JSON document remains only for raw inference provenance,
revision history, word timestamps and attribution metadata. Existing projects
with JSON-only reviews still load; their next save generates a WebVTT track.
You can edit this .vtt in a compatible external subtitle editor and changes to
cues will load again on project reopen. Invalid or duplicate WebVTT cue IDs are
reported rather than silently converted into incorrect subtitles.

Use **Import .vtt/.srt…** in the STT inspector (or File menu) to replace the
**reviewed** cues of an already-transcribed source. Original STT hypotheses
remain unchanged. WebVTT supports cue identifiers, UTF-8 Vietnamese, multiline
text and optional overlapping time ranges. Importing an SRT creates stable
application cue identifiers and can be exported back to .vtt/.srt.

In the **STT** inspector, choose a scope next to **Export transcript…**:
**Current source** (default), **Selected source range**, or **Whole project · clip order**.
Export defaults to `.vtt` with official `WEBVTT` header and dot-separated
millisecond cues. Use `.srt` for broadly compatible numbered comma-timestamp
cues; Markdown/TXT/JSON remain available as reporting or archive formats.
The File → Export transcript menu and transcript context menu use that same action.
After saving, **Open output folder** opens the destination. Source-range export clips
export timestamps to the bottom timeline selection. **All selected export formats exclude untimed boundary speech.** Only
fully contained timestamped words are included from partial segments. If word
timings are unavailable (including after a text edit), boundary text is omitted;
full segments inside the range retain reviewed text. TXT/Markdown include source
provenance. Selected JSON contains only selected reviewed entries plus
source/fingerprint, interval and revision provenance. It excludes raw transcripts,
history and whole-source inference metadata. Partial JSON entries are marked
`text_requires_review`; empty omitted text produces no human-readable line or
subtitle cue. The export status and Help describe this policy. Full-source exports
retain complete reviewed text; full-source JSON retains raw and edited views.

**Whole project** export follows ordered project clips and trims. WebVTT/SRT
use project-relative timestamps; Markdown/TXT use explicit
file/range boundaries and source-relative timestamps. SRT uses project-relative
cue times and source filenames. JSON includes each clip's media ID, source range,
project start and selected reviewed entries, using the same selection policy.
Segment/word times are source seconds; `timeline_start` is project seconds.
Source model timestamps
and stored reviews are not shifted or overwritten by an export.

## Synchronized subtitle review

The existing media preview displays the active **edited** transcript segment as a
compact one- or two-line soft subtitle. It uses the same **source seconds** as
playback, transcript row seeks and speaker/locator overlays, while project clips
still respect their own trim and project timeline mapping. It automatically
updates after edits, split/merge/revert, diarization labels, speaker renaming,
source changes and project reopen. Overlapping segments resolve predictably,
with later-starting segments taking precedence and end times exclusive. Empty
segments and playheads without transcript coverage have no subtitle.

Use **View → Show subtitles** to toggle the overlay (enabled by default).
This preference is stored in the project. SRT files remain separate exports;
subtitles are not embedded into the video.
