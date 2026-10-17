from voice_studio.task_runtime import TaskRequest


def test_stt_request_is_plain_paths_and_options():
    req = TaskRequest(kind="stt", inputs={
        "target_path": "meeting.m4a",
        "options": {"model_id": "whisper-small", "language": "vi", "vad": True},
    })
    assert req.kind == "stt"
