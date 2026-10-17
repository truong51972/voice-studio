# Local Projects and batch transcription

**Projects** in the inspector use a versioned project directory with
\`project.json\`, per-file raw results in \`results/\` and corrections in
\`reviews/\`. Media files are referenced by their absolute path, never
copied/uploaded. The user can import multiple M4A, MP3, WAV or video
files in stable order and start a sequential offline transcription queue.

Each file has a SHA-256 content fingerprint. Cached inference is valid
only when the fingerprint and all model/settings options match. Changing
the model invalidates the cache; completed unchanged files are skipped.
Missing/changed paths require relinking. Jobs interrupted on app exit are
retryable. Manifest/results/reviews use atomic file replacement.

Timestamps always remain relative to their original source file. A
combined Markdown/TXT report is produced **only on explicit Export** and
contains named file boundaries in selected order. User edits are persisted
as separate transcript documents without modifying raw model output.

No database, cloud storage or user account is required. Large media
bytes are not serialized through Qt signals or stored in the manifest.
