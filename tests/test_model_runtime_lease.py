from voice_studio.model_catalog import get_model
from voice_studio.model_service import ModelService
from voice_studio.task_runtime import TaskManager, TaskRequest


def test_model_lease_survives_multiple_queued_jobs_until_acknowledged(tmp_path):
    manager = TaskManager(cpu_concurrency=1, root=tmp_path / "jobs")
    service = ModelService()
    model = get_model("whisper-small")
    request = TaskRequest(kind="editor", inputs={
        "action": "stt", "project_directory": str(tmp_path),
        "target_path": str(tmp_path / "sample.wav"),
        "options": {"model_id": model.id},
    })
    try:
        first = manager.submit(request)
        second = manager.submit(request)
        assert service.busy(model)
        manager.cancel(first)
        manager.acknowledge(first)
        assert service.busy(model)
        manager.cancel(second)
        manager.acknowledge(second)
        assert not service.busy(model)
    finally:
        manager.close()
