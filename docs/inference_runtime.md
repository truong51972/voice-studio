# Inference task runtime

\`TaskManager\` is a standard Python process-isolated queue, driven by nonblocking
\`poll()\`; the Qt \`AnalysisWorker\` bridge emits small state/progress notifications
from a 75ms timer. On Windows it uses the \`spawn\` multiprocessing context.
The app's Locator calls execute in the subprocess instead of Qt's UI thread.
Existing UI and matching math are unchanged.

Per-job input is a JSON-safe payload containing file paths, profile, threshold
and short reference descriptions (never raw PCM). The child saves JSON output
to a temporary directory; the host reconstructs only the segment/similarity
data required for display. The original \`AnalysisBundle.target\` waveform is
intentionally not carried across the process boundary.

States are queued/running/completed/failed/cancelled. \`cancel()\` terminates the
subprocess and cleans temporary artifacts. One GPU slot is always reserved;
CPU concurrency is configurable. The runner does not claim native CUDA support,
inference progress percentage, persistent resume or a remote execution API.

Qt closes the manager on completion/cancellation. The GUI supports Cancel
while the task is running. For real long recordings progress currently indicates
loading/running/completed stages only, because the upstream Locator pipeline
does not provide per-window hooks yet.

Future #6 uses the same subprocess protocol for STT, and #8 introduces
durable project persistence/retry on top of the runner.
