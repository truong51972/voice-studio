import time
from pathlib import Path

import pytest

from voice_studio.task_runtime import TaskManager, TaskRequest, reconstruct_locator


def _wait_for(manager, identifier, timeout=12):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        manager.poll()
        state = manager.snapshot(identifier).state
        if state in ("completed", "failed", "cancelled"):
            return state
        time.sleep(0.08)
    raise TimeoutError("Worker did not settle")

def test_reject_raw_arrays_and_callable_payloads():
    with pytest.raises(TypeError):
        TaskRequest(kind="locator", inputs={"callback": lambda: None})
    with pytest.raises(ValueError):
        TaskRequest(kind="diagnostic", inputs={}, device="tpu")

def test_spawn_child_returns_small_json_artifact(tmp_path):
    mgr = TaskManager(root=tmp_path)
    try:
        job = mgr.submit(TaskRequest(kind="diagnostic", inputs={"seconds": 0.05, "value": "ok"}))
        assert _wait_for(mgr, job) == "completed"
        assert mgr.result(job) == {"kind": "diagnostic", "value": "ok"}
        assert mgr.snapshot(job).progress == 1
        mgr.acknowledge(job)
        assert not (tmp_path / job).exists()
    finally:
        mgr.close()

def test_cancel_running_worker_and_clean_files(tmp_path):
    mgr = TaskManager(root=tmp_path)
    try:
        job = mgr.submit(TaskRequest(kind="diagnostic", inputs={"seconds": 5}, device="gpu"))
        mgr.poll()
        assert mgr.snapshot(job).state == "running"
        mgr.cancel(job)
        assert mgr.snapshot(job).state == "cancelled"
        assert not (tmp_path / job).exists()
    finally:
        mgr.close()

def test_gpu_serialization(tmp_path):
    mgr = TaskManager(cpu_concurrency=3, root=tmp_path)
    try:
        first = mgr.submit(TaskRequest(kind="diagnostic", inputs={"seconds": 0.4}, device="gpu"))
        second = mgr.submit(TaskRequest(kind="diagnostic", inputs={"seconds": 0.4}, device="gpu"))
        mgr.poll()
        assert mgr.snapshot(first).state == "running"
        assert mgr.snapshot(second).state == "queued"
        assert _wait_for(mgr, first) == "completed"
        assert _wait_for(mgr, second) == "completed"
    finally:
        mgr.close()

def test_compact_locator_reconstruction():
    payload = {
        "media_kind": "audio", "duration": 5,
        "results": [{
            "key": "a", "name": "Speaker 1", "scores": [],
            "segments": [{"start": 1, "end": 2, "avg_score": .7, "max_score": .8}],
            "matched_duration": 1, "coverage": 20, "max_score": .8
        }]
    }
    bundle = reconstruct_locator(payload)
    assert bundle.target.size == 0
    assert bundle.results[0].segments[0].start == 1
