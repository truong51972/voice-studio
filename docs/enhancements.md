# Optional post-MVP enhancements (#11)

This module is entirely opt-in. Neither media nor transcript text is sent
to any cloud API by default.

**Local summary:** Use a *locally running* Ollama model (e.g., a model you
previously pulled) to produce a Markdown meeting report from the **reviewed**
transcript. Source segment IDs and start/end times are supplied with every
request. Generated items referencing missing/out-of-scope IDs are discarded.
All remaining prose is visibly labeled **AI-generated draft — verify against
source**; it is not claimed as verbatim recorded speech. Raw STT output and
user corrections remain unchanged. Provenance includes transcript revision,
SHA256 snapshot, local provider/model and timestamp.

**Denoise evaluation:** \`denoise_media(input, distinct_output.wav)\` uses
FFmpeg \`afftdn\` to write a new file without overwriting the source.
Compare transcript WER/CER on the same human transcript before/after via
\`voice_studio.quality\`. There is no unsupported promise that denoising
improves recognition: aggressive filters may remove quiet speech.

No Ollama server is started or model downloaded automatically. A local
model must be available on loopback \`127.0.0.1:11434\`. Cloud LLM providers
are intentionally *not* integrated in this first optional enhancement.

The project editor's **Whole project** scope builds an ordered, trimmed review
snapshot for a local summary. Every cited segment ID includes its clip ID; each
item retains media ID, external source and source-relative start/end anchors.
Repeated/independent source clocks therefore remain distinguishable. Summary
snapshots and drafts live within the project and do not change STT/review data.
