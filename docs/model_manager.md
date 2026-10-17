# Model registry and local assets

Model Manager (toolbar) lists task-scoped Locator and STT models. Locator profiles
remain the original SHA-256-verified CAM++ and ERes2NetV2, including unchanged
thresholds. STT model choices are *not* automatically installed or loaded.

To enable STT backends, run \`uv sync --extra stt\`. Open **Models** in
the app and install one model. Downloads are explicit and run outside the GUI
thread. STT snapshots are placed in the per-user writable data directory, not
the executable directory (override \`VOICE_STUDIO_MODEL_DIR\` for testing).

**Integrity:** installed STT assets are from the resolved Hugging Face commit;
the manifest records the commit and local SHA-256 digests, and validates them
on next use. These digests are **locally computed**, not publisher-signed.
Users should review each model card/license and publisher. No external network
access occurs during ordinary startup/status checks; snapshots are fetched
only by explicit installation. Re-running downloads uses Hugging Face's cache
(resume/retry behavior depends on the backend). Partial installations are kept
out of the model registry.

A CUDA option is not marked ready by a mere import check. CPU is the safe
default; CUDA requires an actual backend/driver/DLL smoke test.
