"""Review-friendly timeline refresh and source-list glanceability."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from voice_studio.projects import ProjectStore
from voice_studio.ui import build_app, create_application


def _project(tmp_path):
    media = tmp_path / "conference.wav"
    media.write_bytes(b"placeholder source")
    project = ProjectStore(tmp_path / "project")
    project.add([media])
    project.items[0].duration = 4560.
    return project, project.items[0]


def test_source_list_summarizes_done_tasks_and_human_duration(tmp_path):
    app = create_application([])
    project, item = _project(tmp_path)
    project.begin(item.id, {})
    project.complete(item.id, {
        "kind": "stt", "source": item.source, "duration": 4560., "segments": [],
    })
    project.queue_analysis(item.id, "diarization", {})
    window = build_app()
    try:
        window.session.project = project
        window.projects_panel._refresh()
        assert window.projects_panel.table.item(0, 2).text() == "1:16:00"
        assert "STT ✓" in window.projects_panel.table.item(0, 1).text()
        assert "diarization" in window.projects_panel.table.item(0, 1).text()
        assert "stt: completed" in window.projects_panel.table.item(0, 0).toolTip()
    finally:
        window.close()
        app.processEvents()


def test_correcting_transcript_does_not_full_rebuild_or_reload_waveforms(tmp_path, monkeypatch):
    app = create_application([])
    project, item = _project(tmp_path)
    window = build_app()
    try:
        window.session.project = project
        window._clip_id = project.clips[0].id
        window.timeline.set_project_data(project.timeline(), [], [
            {"start": 1., "end": 2., "lane": "Transcript", "text": "Raw",
             "kind": "transcript", "media_id": item.id, "overlap": False},
            {"start": 2., "end": 3., "lane": "Speaker 1", "text": "Speaker 1",
             "kind": None, "media_id": item.id, "overlap": False},
        ])
        window.stt_panel._show({
            "kind": "stt", "source": item.source, "duration": item.duration,
            "segments": [{"id": "a", "start": 1., "end": 2., "text": "Raw"}],
        })
        window.stt_panel.document.replace("a", text="Edited")
        def full_rebuild_forbidden():
            raise AssertionError("Text review must not recreate all source waveform tracks")
        monkeypatch.setattr(window, "_render_timeline", full_rebuild_forbidden)
        window._update_review_timeline()
        updated = window.timeline._annotations
        assert len(updated) == 2
        assert next(a for a in updated if a["kind"] == "transcript")["text"] == "Edited"
        assert next(a for a in updated if a["lane"] == "Speaker 1")["text"] == "Speaker 1"
    finally:
        window.close()
        app.processEvents()
