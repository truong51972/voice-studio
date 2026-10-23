"""End-user partial transcript recovery without running a real GPU model."""
from types import SimpleNamespace

from voice_studio.storage import atomic_json
from voice_studio.ui.session import ProjectSession


def _source(tmp_path):
    item = SimpleNamespace(
        id="source1", source="D:/Downloads/talk.mp4", fingerprint="original-contents",
        duration=1800.,
    )
    project = SimpleNamespace(directory=tmp_path, get=lambda media_id: item)
    options = {"model_id": "whisper-large-v3-turbo", "language": "en",
               "model_revision": [["model.bin", 123, 456]]}
    record = SimpleNamespace(task="stt", media_id=item.id, settings=options)
    return project, item, record


def test_project_partial_transcript_survives_failure_and_checks_signature(tmp_path):
    project, item, record = _source(tmp_path)
    path = ProjectSession._stt_checkpoint_path(project, item, record.settings)
    payload = {"schema": 1, "signature": {
        "source": item.source,
        "options": {k: v for k, v in record.settings.items() if k != "model_revision"},
    }, "processed_seconds": 60., "segments": [
        {"id": "s000001", "start": .2, "end": 1.4, "text": "Hello",
         "speaker_id": None, "words": [], "language": "en"},
    ], "language": "en", "warnings": ["timestamp corrected"],
       "warning_count": 1}
    atomic_json(path, payload)

    session = ProjectSession()
    session.project = project
    result = session.partial_transcript(record)
    assert result["partial"]
    assert result["duration"] == 60.
    assert result["segments"][0]["text"] == "Hello"
    assert result["warning_count"] == 1

    record.settings["language"] = "vi"
    assert session.partial_transcript(record) is None
    assert ProjectSession._stt_checkpoint_path(project, item, record.settings) != path
    record.settings["language"] = "en"
    item.fingerprint = "modified-contents"
    assert ProjectSession._stt_checkpoint_path(project, item, record.settings) != path
    assert session.partial_transcript(record) is None
