"""Process-isolated serializable jobs; no Qt imports and no PCM in IPC.

Only paths/scalar settings are passed to the child. Locator result is a compact
JSON artifact on disk: previews and plot data are restored in the UI process.
"""
from __future__ import annotations

import json
import multiprocessing as mp
import os
import shutil
import tempfile
import time
import traceback
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

TaskState = Literal["queued", "running", "completed", "failed", "cancelled"]

@dataclass(frozen=True)
class TaskRequest:
    kind: Literal["locator", "diagnostic"]
    inputs: dict
    device: Literal["cpu", "gpu"] = "cpu"
    def __post_init__(self):
        if self.device not in ("cpu", "gpu"):
            raise ValueError("Unknown task device")
        if self.kind not in ("locator", "diagnostic"):
            raise ValueError("Unknown task kind")
        # Never marshal sample arrays, model instances, Qt widgets or arbitrary callables.
        def plain(x):
            return x is None or type(x) in (str, float, int, bool) or (
                type(x) is list and all(plain(y) for y in x)
            ) or (type(x) is dict and all(type(k) is str and plain(v) for k, v in x.items()))
        if not plain(self.inputs):
            raise TypeError("Task input must be JSON-safe paths, lists and scalar options")

@dataclass
class TaskSnapshot:
    id: str
    state: TaskState
    progress: float = 0.0
    stage: str = "Queued"
    error: str | None = None
    started_at: float | None = None
    ended_at: float | None = None

def _child_entry(request: TaskRequest, artifact: str) -> None:
    """Top-level spawn-safe child entry. Only this process loads inference backends."""
    folder = Path(artifact)
    try:
        (folder / "status.json").write_text(json.dumps({"stage": "Loading model"}))
        if request.kind == "diagnostic":
            delay = float(request.inputs.get("seconds", 0.0))
            time.sleep(min(max(delay, 0), 10))
            payload = {"kind": "diagnostic", "value": str(request.inputs.get("value", ""))}
        else:
            from .service import LocatorService
            refs = [(str(item[0]), None if item[1] is None else str(item[1])) for item in request.inputs["references"]]
            source = str(request.inputs["target_path"])
            media_kind = str(request.inputs["media_kind"])
            profile = str(request.inputs["profile"])
            bundle, threshold = LocatorService().analyze(
                refs,
                None if media_kind == "video" else source,
                source if media_kind == "video" else None,
                float(request.inputs["threshold"]),
                profile_key=profile,
            )
            payload = {
                "kind": "locator",
                "media_kind": bundle.media_kind,
                "duration": bundle.duration,
                "threshold": threshold,
                "profile": profile,
                "scenario": request.inputs.get("scenario", ""),
                "results": [
                    {
                        "key": r.key, "name": r.name,
                        "scores": [asdict(s) for s in r.scores],
                        "segments": [asdict(s) for s in r.segments],
                        "matched_duration": r.matched_duration,
                        "coverage": r.coverage, "max_score": r.max_score,
                    }
                    for r in bundle.results
                ],
            }
        temp = folder / "result.part"
        with temp.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, allow_nan=False)
        os.replace(temp, folder / "result.json")
    except BaseException as exc:
        try:
            (folder / "error.json").write_text(json.dumps({
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc()[-2000:],
            }), encoding="utf-8")
        except OSError:
            pass

class _Task:
    def __init__(self, identifier: str, request: TaskRequest, folder: Path):
        self.request = request
        self.folder = folder
        self.snapshot = TaskSnapshot(id=identifier, state="queued")
        self.process: mp.Process | None = None

class TaskManager:
    """Launch at most one GPU task and cpu_concurrency CPU jobs at a time.

    Explicit poll() lets either Qt QTimer or a synchronous test drive the queue.
    Cancel terminates a child and deletes its temporary artifacts. Always close
    the manager on shutdown to avoid orphan processes.
    """
    def __init__(self, *, cpu_concurrency: int = 2, root: Path | None = None):
        if cpu_concurrency < 1:
            raise ValueError("CPU concurrency must be >= 1")
        self.cpu_concurrency = cpu_concurrency
        self.root = root if root is not None else Path(tempfile.mkdtemp(prefix="voice-studio-jobs-"))
        self._owns_root = root is None
        self.root.mkdir(parents=True, exist_ok=True)
        self._context = mp.get_context("spawn")
        self._tasks: dict[str, _Task] = {}

    def submit(self, request: TaskRequest) -> str:
        identifier = uuid.uuid4().hex
        folder = self.root / identifier
        folder.mkdir(parents=True)
        self._tasks[identifier] = _Task(identifier, request, folder)
        return identifier

    def poll(self) -> tuple[TaskSnapshot, ...]:
        # Reap terminated jobs before scheduling new ones.
        for task in self._tasks.values():
            state = task.snapshot
            proc = task.process
            if state.state != "running" or proc is None:
                continue
            if proc.is_alive():
                status = task.folder / "status.json"
                if status.exists():
                    try:
                        state.stage = json.loads(status.read_text()).get("stage", "Running")
                        state.progress = 0.1
                    except (ValueError, OSError):
                        pass
                continue
            proc.join(timeout=0.2)
            proc.close()
            task.process = None
            state.ended_at = time.monotonic()
            result = task.folder / "result.json"
            error = task.folder / "error.json"
            if result.exists():
                state.state = "completed"
                state.progress = 1.0
                state.stage = "Completed"
            else:
                state.state = "failed"
                state.stage = "Failed"
                if error.is_file():
                    try:
                        state.error = json.loads(error.read_text()).get("error")
                    except (ValueError, OSError):
                        pass
                if not state.error:
                    state.error = "Worker exited before writing results (crash or missing runtime)"
        for task in self._tasks.values():
            if task.snapshot.state != "queued":
                continue
            active = sum(
                int(t.snapshot.state == "running" and t.request.device == task.request.device)
                for t in self._tasks.values()
            )
            capacity = 1 if task.request.device == "gpu" else self.cpu_concurrency
            if active >= capacity:
                continue
            try:
                proc = self._context.Process(
                    target=_child_entry, args=(task.request, str(task.folder)),
                    daemon=False,
                )
                proc.start()
            except Exception as exc:
                task.snapshot.state = "failed"
                task.snapshot.error = f"Cannot start inference worker: {exc}"
                task.snapshot.ended_at = time.monotonic()
                continue
            task.process = proc
            task.snapshot.state = "running"
            task.snapshot.started_at = time.monotonic()
            task.snapshot.stage = "Starting subprocess"
        return tuple(t.snapshot for t in self._tasks.values())

    def snapshot(self, identifier: str) -> TaskSnapshot:
        return self._tasks[identifier].snapshot

    def result(self, identifier: str) -> dict:
        task = self._tasks[identifier]
        if task.snapshot.state != "completed":
            raise RuntimeError("Task has not completed successfully")
        return json.loads((task.folder / "result.json").read_text(encoding="utf-8"))

    def cancel(self, identifier: str) -> None:
        task = self._tasks[identifier]
        if task.snapshot.state not in ("queued", "running"):
            return
        proc = task.process
        if proc is not None:
            if proc.is_alive():
                proc.terminate()
            proc.join(timeout=3)
            if proc.is_alive():
                proc.kill()
                proc.join(timeout=3)
            proc.close()
            task.process = None
        task.snapshot.state = "cancelled"
        task.snapshot.ended_at = time.monotonic()
        task.snapshot.stage = "Cancelled"
        shutil.rmtree(task.folder, ignore_errors=True)

    def acknowledge(self, identifier: str) -> None:
        task = self._tasks[identifier]
        if task.snapshot.state in ("queued", "running"):
            raise RuntimeError("Cannot delete active task")
        self._tasks.pop(identifier)
        shutil.rmtree(task.folder, ignore_errors=True)

    def close(self) -> None:
        for identifier in list(self._tasks):
            if self.snapshot(identifier).state in ("queued", "running"):
                self.cancel(identifier)
            self.acknowledge(identifier)
        if self._owns_root:
            shutil.rmtree(self.root, ignore_errors=True)

def reconstruct_locator(payload: dict):
    """Restore display-only result objects without reintroducing raw PCM arrays."""
    import numpy as np
    from .localization import MatchSegment, WindowScore
    from .pipeline import AnalysisBundle, SpeakerResult
    results = [
        SpeakerResult(
            key=r["key"], name=r["name"],
            scores=[WindowScore(**v) for v in r["scores"]],
            segments=[MatchSegment(**v) for v in r["segments"]],
            matched_duration=r["matched_duration"],
            coverage=r["coverage"], max_score=r["max_score"],
        )
        for r in payload["results"]
    ]
    return AnalysisBundle(
        target=np.empty(0, dtype=np.float32),
        media_kind=payload["media_kind"], duration=payload["duration"],
        results=results,
        scores_by_name={r.name: r.scores for r in results},
        segments_by_name={r.name: r.segments for r in results},
    )
