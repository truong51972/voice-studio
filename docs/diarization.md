# Optional diarization (issue #9)

Known-speaker Locator remains unchanged. Unknown-speaker diarization is a
separate *optional* local task; it is not speaker identification.

- Install application runtimes (\`uv sync --locked\`) and a
  complete, locally available Community-1 model from
  [pyannote](https://huggingface.co/pyannote/speaker-diarization-community-1).
- Accept upstream license/terms and download on your own workstation.
  Voice Studio never asks for a token or silently downloads the model.
- Open media in Workspace, then select the **Diarization** inspector.
  Browse to the model folder containing \`config.yaml\` and press Analyze.
- The subprocess creates a temporary 16k mono WAV via local FFmpeg,
  runs \`Pipeline.from_pretrained(local_path)\` with Hugging Face offline mode,
  and returns anonymous turns (\`Speaker 1\`, etc.).
- Community-1 exclusive diarization, when exposed, is used for
  reconciliation. Overlap, unknown confidence and short segments are not
  presented as verified identities or certainty.
- Apply the suggested attributions to the **editable** transcript only;
  raw Whisper hypotheses remain immutable and manual speaker edits can
  override assignments. Source timebase is unchanged.

This code path requires hands-on real-model, multi-speaker and Windows
runtime testing before marking support as validated. Python runtimes are
included in the default installation and packaging; gated weights remain
user-managed. TorchCodec also needs compatible native FFmpeg shared libraries;
the bundled FFmpeg executable alone does not prove that it can decode audio.
