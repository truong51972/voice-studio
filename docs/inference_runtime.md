# Inference task runtime

## Default installation and platform checks

`uv sync --locked` installs every production Python runtime: PySide6/media,
sherpa-onnx, faster-whisper/CTranslate2, Hugging Face and pyannote/Torch.
There are no feature extras or reduced-runtime build variants. Development,
test and build tools remain in the default `dev` group; weights remain explicit
user installations. `uv run poe start` launches without downloading weights.

The target matrix is **Windows x64 and Linux x64, Python 3.11 and 3.12**.
The lock requires compatible wheels for both targets and CI runs the same
model-free test and import commands on each. This is a configured test matrix,
not a record that all four CI jobs or clean-machine release QA have passed.
Linux x64/Python 3.12 was checked locally for this foundation change.
macOS (including Apple Silicon), Windows ARM and Linux ARM are outside the
current matrix. In particular modern Torch/pyannote does not support the
previous Intel macOS lock target; other untested platforms are not advertised.

Torch and torchaudio use the explicit PyTorch CPU index, constrained to the
2.8 series together with TorchCodec 0.7, following the
[TorchCodec compatibility matrix](https://github.com/meta-pytorch/torchcodec#compatibility-with-torch-versions).
This avoids mismatched native release families and automatic Linux CUDA
toolkit downloads. CUDA, GPU memory, drivers and CTranslate2 DLLs require
separate real-hardware verification and are not a supported release baseline.

Run the same verification commands in a Linux shell or Windows PowerShell:

```sh
uv sync --locked
uv run python -m voice_studio.diagnostics --check-runtimes
uv run poe check
uv run poe test
```

Qt tests set `QT_QPA_PLATFORM=offscreen` internally. Normal startup checks for
missing Python packages without importing inference backends; the explicit
`--check-runtimes` command actually imports native backends, reports all import
failures and exits nonzero on failure. Neither downloads models. A native
import check does not prove that a model can load or perform inference.

**Native release gap:** TorchCodec 0.7 decoding needs compatible FFmpeg 4–7
shared libraries. The imageio-ffmpeg executable is sufficient for the app's
FFmpeg subprocesses but is not a replacement for those libraries. Native
library bundling and clean Windows runtime/model-load smoke tests remain
required before signing off a package. The stricter build check fails instead
of silently omitting a runtime. Real-model STT/Community-1, CUDA, microphone and
native media playback have not been verified by this foundation change.

## Task isolation

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
