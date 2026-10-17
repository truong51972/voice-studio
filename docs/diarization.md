# Optional diarization (issue #9)

Known-speaker Locator remains unchanged. Unknown-speaker diarization is a
separate *optional* local task; it is not speaker identification.

- Install the optional Python runtime (\`uv sync --extra diarization\`) and a
  complete, locally available Community-1 model from
  [pyannote](https://huggingface.co/pyannote/speaker-diarization-community-1).
- Accept upstream license/terms and download on your own workstation.
  Voice Studio never asks for a token or silently downloads the model.
- Open media in Workspace, then select the **Diarization** inspector.
  Browse to the model folder containing \`config.yaml\` and press Analyze.
- The subprocess creates a temporary 16k mono WAV via local FFmpeg,
  runs \`Pipeline.from_pretrained(local_path)\` with Hugging Face offline mode,
  and returns anonymous turns (\`Speaker 1\`, etc.).
- Original Community-1 turns are retained in `turns` for overlap-aware display.
  Separate `exclusive_turns`, when exposed, are used for transcript assignment.
  Both share the same source-local cluster mapping and retain `cluster_id`;
  one file's anonymous labels never establish another file's speaker identity.
  When exclusive output is absent, conservative attribution uses the original
  turns and leaves overlapping turns unassigned. Unknown confidence remains null.
- Apply the suggested attributions to the **editable** transcript only;
  raw Whisper hypotheses remain immutable and manual speaker edits can
  override assignments. Source timebase is unchanged.

This code path requires hands-on real-model, multi-speaker and Windows
runtime testing before marking support as validated. Heavy dependencies
are not installed in the default package or model-free CI.

Issue #26 will make Auto Detect the default Speakers workflow and add persistent
project speaker mappings and manual source-interval references. That GUI work is
pending; see [implementation status](project_workspace_refactor.md).
