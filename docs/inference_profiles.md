# Inference accuracy profiles

AI Voice Studio exposes user-facing inference profiles instead of asking users to choose raw model files.

## Profiles

| Profile | Speaker model | Model size | Intended use |
|---|---|---:|---|
| `fast` | CAM++ VoxCeleb | ~28.2 MiB | Default CPU-first analysis and quick iteration |
| `accurate` | ERes2NetV2 common | ~68.1 MiB | Higher-capacity speaker embedding when latency is less important |

Both models run locally through `sherpa-onnx`. `uv run poe models` downloads and verifies every configured profile model before packaging.

## Thresholds are profile configuration

Cosine-similarity distributions are model-dependent. A threshold that works for CAM++ must not be assumed to be optimal for ERes2NetV2.

The code therefore stores `default_threshold` on each inference profile and lets the UI reset the threshold when the selected profile changes. For the initial implementation both profiles intentionally keep `0.60` as a conservative baseline so the project does not claim an unmeasured accuracy gain.

Before changing the `accurate` default, calibrate it on held-out classroom/Vietnamese recordings and report at least Precision, Recall and F1 across a threshold sweep.

## What this PR does not claim

`accurate` means a higher-capacity inference path, not a guaranteed higher accuracy score for every recording. Model size alone is not sufficient evidence of better performance on Vietnamese classroom audio.

Recommended follow-up experiments:

1. Compare `fast` and `accurate` on the same labeled recordings.
2. Sweep thresholds independently per profile.
3. Stratify results by reference duration and noise level.
4. Compare multiple source reference regions per project speaker with a single clean interval.
5. Evaluate VAD-based speech gating against the current RMS gate.
6. Only add a `maximum`/ensemble profile if the benchmark shows a meaningful gain over ERes2NetV2.

## Extension contract

New profiles belong in `src/voice_studio/profiles.py`. Each entry owns:

- a stable profile key and user-facing label;
- model filename, exact size and SHA-256;
- download mirrors;
- default threshold;
- runtime thread count.

The analysis pipeline resolves the profile once, caches an embedder per profile, and keeps the rest of localization/scoring unchanged. This keeps model selection separate from speaker matching logic.
