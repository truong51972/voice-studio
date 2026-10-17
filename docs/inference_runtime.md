# Inference task runtime

The PySide6 editor injects one `ProjectSession` into its panels. Its single
`TaskManager(cpu_concurrency=1)` serializes project work, including optional
CPU/GPU-backed models, instead of launching competing managers per inspector.
The generic runtime and standalone legacy panel APIs remain available to callers.

Workers use the spawn multiprocessing context. Requests carry paths, IDs and
scalar settings, never PCM or live model/Qt objects. Import/probe/fingerprint,
waveform peaks, bounded source references, streamed Locator, STT, diarization,
comparison and local summaries all run outside the UI thread. Summary input is a
cached review-snapshot path. Original/exclusive speaker turns and edited reviews
remain distinct from immutable raw results.

Staging lives in `<project>/cache/jobs/<job-id>/`; successful analysis outputs are
atomically committed to `results/` and revisions to `reviews/`. No project data
uses an OS profile or system temporary folder. The separate model/runtime caches
retain their previous storage contract. The historical generic non-project runner
may still use temporary folders when invoked directly by other callers.

The nonblocking Qt timer polls queued/running/completed/failed/cancelled states and
worker stage messages (not invented percentage estimates). Project jobs and import
operation states persist; reopening changes active states to interrupted and
checks source bytes in a worker. Retry uses normal task controls. Cached activation
checks fingerprints asynchronously and performs no model inference. Moving or
trimming clips does not change source inference keys.

Cancel terminates the worker process tree (POSIX process group / Windows taskkill),
reaps the process and removes only staging artifacts. Changing projects cancels
old jobs before replacing their session, so late outputs cannot enter the new
project. Shutdown saves the project and leaves results/reviews/caches intact.

Native Windows process cleanup, codecs, optional pyannote/Torch/CUDA and real
long-recording memory/throughput require explicit release QA. Synthetic streaming
regressions certify bounded PCM/timestamp contracts, not real-model performance.
