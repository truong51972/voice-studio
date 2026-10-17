# Auto Detect and manual speaker references

**Auto Detect is the default Speakers workflow.** It discovers anonymous source
clusters with an explicitly installed local Community-1 model. Clustering does
not verify anyone's identity; optional manual matching finds similar known voices
and does not perform unrestricted speaker discovery.

## Auto Detect

1. Install the optional source runtime: `uv sync --dev --extra diarization`.
2. Obtain a complete local [Community-1 model](https://huggingface.co/pyannote/speaker-diarization-community-1),
   accepting its upstream terms yourself, with all dependencies available locally.
3. New/Open a project and import audio/video. In **Speakers → Auto Detect**, Browse
   to its `config.yaml` folder and select **Auto Detect Speakers**. Toolbar scope
   chooses one source or the whole project (serialized jobs).

No token is requested, model downloaded or cloud API called by analysis.
Missing/incompatible runtime/assets produce an error and a retryable project job.
Packaged builds can explicitly bundle the runtime using `--with-diarization`;
Community-1 assets remain separate. See [Windows release](windows_release.md).

Original `turns` retain overlapping voices for source/annotation tracks.
`exclusive_turns` uses the same source-local `cluster_id` mapping and is used for
transcript attribution. When exclusive output is absent, attribution remains
conservative and skips overlap. Unavailable confidence remains null. Raw turns
are inspectable under **Raw AI**, separately from project speaker names and
human transcript corrections.

Each independent source/analysis has its own mapping to project speaker IDs.
Two “Speaker 1” outputs are never silently treated as one person. Rename or change
track color from the speaker selector. Merge/split requires confirmation; confirmed
aliases/mappings survive reopen, relink of identical bytes and clip reorder.
Speaker corrections in an existing transcript are retained during auto assignment.

## Manual references (no pyannote requirement)

1. Select any imported source. Drag a range on its timeline waveform, or type
   precise source start/end in the bottom selection controls or Manual inspector.
2. **Preview selection/interval** uses the original media and stops at its end.
   It can preview outside a project trim; the source clock remains explicit.
3. Choose **Add manual reference**, select an existing speaker or type a new label,
   audition a single clear voice, then confirm that selection in the checkbox.
4. **Add manual reference** validates source bounds and known overlap, and queues
   bounded FFmpeg region decoding/embedding. Silence/quiet or too-short selections
   fail with guidance. Usually 3–10 seconds is useful guidance, not a proven
   accuracy threshold. Without diarization, overlap cannot be automatically ruled
   out; listen to the selection. The app rejects overlap once it is known.
5. Collect multiple regions per speaker if useful. Failed/cancelled references have
   **Retry selected reference**; changed media require a new selection.
6. Choose CAM++/ERes2NetV2 and threshold in **Analysis**, then **Match references**
   (selected source or whole project). No trimmed WAV upload/export is needed.

References persist media ID, source seconds, fingerprint and model revision.
Derived embeddings are cached by content/range/verified model SHA; source/model
changes cannot reuse stale vectors. Matching uses bounded rolling target windows.
A reference can refine/validate an existing auto speaker by being assigned to it;
match sections remain hypotheses, separately from original diarization.

## Cross-source reconciliation

**Merge proposals → Compare project speakers** uses clean representative intervals
and/or ready manual references to suggest similar project speakers. Scores are
cosine similarity, not calibrated confidence. Multiple plausible candidates are
marked ambiguous. Review each proposal, **Confirm merge…** or **Reject**; no
proposal automatically merges speakers. Confirmed project aliases also resolve
historical Locator outputs/review IDs without overwriting raw inference.

Real Community-1/embedding accuracy, multi-speaker audio, optional native runtime
packaging and long-recording resource behavior still require hands-on sign-off.
Deterministic tests and GUI fixture screenshots are not real-model evidence.

The adapter disables [pyannote's documented usage telemetry](https://github.com/pyannote/pyannote-audio#telemetry)
(`PYANNOTE_METRICS_ENABLED=0`) and Hugging Face telemetry before importing the
optional runtime, and forces offline model loading. These settings are also
covered by a model-free import-boundary regression.
