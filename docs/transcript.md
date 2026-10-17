# Transcript review and export

The STT panel supports searching segment text, click-to-seek, text edits,
manual speaker labels, split/merge adjacent segments and reverting all edits.
Raw STT hypotheses remain immutable in \`TranscriptDocument.raw\`; edits
are a separate revisioned view. Any word timestamps belonging to edited
text are cleared because they would otherwise be misleading.

Exports: TXT, SRT, Markdown and JSON, with media source provenance, coherent
media-local timestamps and any user corrections. JSON contains both raw
inference and edited segments. SRT uses valid \`HH:MM:SS,mmm\` timestamps
and sequential cue numbering. Empty text is omitted.

Split places the original text in the first segment and an empty second
segment for manual review, rather than inventing the content of the split.
Merging two differently attributed speakers resets speaker attribution to
unknown. Transcripts in multiple source files remain independent (#8).
