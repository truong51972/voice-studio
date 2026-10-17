# Model registry and local assets

Model Manager (toolbar) lists task-scoped Locator, STT and Community-1 definitions. Locator profiles
remain the original SHA-256-verified CAM++ and ERes2NetV2, including unchanged
thresholds. STT model choices are *not* automatically installed or loaded.

All production Python backends are installed by \`uv sync --locked\`. Open **Models** in
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

## Catalog and packaging

`configs/models/speaker_matching.json`, `stt.json` and `diarization.json` are
the single source for model IDs, display names, sources/revisions, required
assets, license/access notes, capabilities and inference defaults. Each file
uses `schema_version: 1`; `model_catalog.py` validates the supported engine
IDs, safe asset paths, profile metadata, unique IDs and one default per task.
Invalid catalog diagnostics include the filename and failing field. Adding a
compatible Whisper or speaker-embedding model uses JSON; backend Python modules
cannot be selected or imported from arbitrary catalog strings.

The wheel includes these same files at `voice_studio/configs/models/`;
PyInstaller includes them under `_internal/voice_studio/configs/models/`.
The application owns the speaker downloader in `model_download.py` and never
imports a script from a developer checkout. `scripts/download_models.py` is
only a developer entrypoint. No weights are Python dependencies.

Community-1 retains its existing manual local-folder workflow in the
**Diarization** inspector. Its catalog entry explains the access prerequisites;
automatic installation is disabled. A `config.yaml` is an entrypoint, not
proof that all referenced gated weights are present or loadable.

## Remaining issue #28 work

This is the catalog/runtime foundation of [issue #28](https://github.com/truong51972/voice-studio/issues/28).
Portable `.models/` and `.settings/` storage, safe legacy imports, the unified
model service/manifest, separate present/verified/ready states, cancellable
transfers, readiness workers and **Settings → Models** are still pending.
The editor's menu/action/shortcut refactor is also pending. Current status
checks still hash installed files; they must move off the GUI thread in the
lifecycle work. The existing storage locations are documented above to avoid
suggesting that migration has already happened. Delivery remains one cohesive
refactor PR, with the issue open until acceptance gates are met.
