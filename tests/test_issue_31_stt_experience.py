"""Regression coverage for issue #31: completed progress, export, soft subtitles."""
import json
import os
from types import SimpleNamespace

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from voice_studio.stt import SAMPLE_RATE, STTOptions, transcribe
from voice_studio.subtitle_index import SubtitleIndex
from voice_studio.task_runtime import TaskManager, TaskRequest
from voice_studio.transcript import TranscriptDocument
from voice_studio.ui import build_app, create_application
from voice_studio.ui.panels.stt import STTPanel


def test_lazy_whisper_generator_does_not_advance_until_fully_consumed():
    events = []
    seen_inside_generator = []

    class FakeWhisper:
        def transcribe(self, samples, **_kwargs):
            def lazy_segments():
                seen_inside_generator.append(events[-1]["processed_seconds"])
                yield SimpleNamespace(start=0., end=.5, text="Xin chào", words=None)
                seen_inside_generator.append(events[-1]["processed_seconds"])
            return lazy_segments(), SimpleNamespace(language="vi")

    chunks = [(0., np.ones(SAMPLE_RATE * 5, dtype=np.float32) * .1),
              (5., np.zeros(SAMPLE_RATE * 5, dtype=np.float32)),
              (10., np.ones(SAMPLE_RATE * 5, dtype=np.float32) * .1)]
    result = transcribe("fixture.wav", STTOptions(), engine=FakeWhisper(),
                        chunks=chunks, total_seconds=15., progress=events.append)
    assert result["duration"] == 15.
    assert seen_inside_generator == [0., 0., 10., 10.]
    completed = [e["processed_seconds"] for e in events if e["stage"] in
                 ("Audio processed", "Skipping silence")]
    assert completed == [5., 10., 15.]
    assert all(a <= b for a, b in zip(completed, completed[1:]))
    assert all(e["total_seconds"] == 15. for e in events)
    assert events[-1]["stage"] == "Finalizing transcript"


def test_indeterminate_and_zero_duration_do_not_invent_percent():
    events = []
    class Fake:
        def transcribe(self, chunk, **kwargs):
            return iter([]), SimpleNamespace(language="vi")
    transcribe("fixture.wav", STTOptions(), engine=Fake(),
               chunks=[(0., np.ones(SAMPLE_RATE * 5, dtype=np.float32))],
               total_seconds=0, progress=events.append)
    assert all(e["total_seconds"] is None for e in events)
    assert events[-1]["processed_seconds"] == 5.


def test_runtime_snapshot_reads_structured_status_safely(tmp_path):
    manager = TaskManager(root=tmp_path)
    try:
        job = manager.submit(TaskRequest(kind="diagnostic", inputs={}))
        task = manager._tasks[job]
        status = task.folder / "status.json"
        status.write_text(json.dumps({"stage": "Audio processed",
                                      "processed_seconds": 15.,
                                      "total_seconds": 30.}))
        manager._update_progress(task)
        assert manager.snapshot(job).progress == pytest.approx(.5)
        assert manager.snapshot(job).processed_seconds == 15.
        status.write_text(json.dumps({"stage": "Slow job",
                                      "processed_seconds": 10.,
                                      "total_seconds": 30.}))
        manager._update_progress(task)
        assert manager.snapshot(job).progress >= .5
        status.write_text('{"partial":')
        manager._update_progress(task)
        assert manager.snapshot(job).progress >= .5
        status.write_text(json.dumps({"stage": "bad", "processed_seconds": -1,
                                      "total_seconds": 0}))
        manager._update_progress(task)
        assert manager.snapshot(job).progress >= .5
    finally:
        manager.close()


def _doc():
    return TranscriptDocument({"kind": "stt", "source": "talk.wav",
        "segments": [
            {"id": "first", "start": 1., "end": 3., "text": "Xin chào"},
            {"id": "overlap", "start": 2., "end": 4., "text": "Chào cả lớp", "speaker_id": "a"},
            {"id": "blank", "start": 4., "end": 5., "text": " "},
            {"id": "last", "start": 5., "end": 6., "text": "Kết thúc"},
        ]})


def test_subtitle_lookup_is_source_relative_with_overlaps_and_boundaries():
    document = _doc()
    index = SubtitleIndex(document.edited)
    assert index.at(.999) is None
    assert index.at(1.).id == "first"
    assert index.at(2.).id == "overlap"  # later start wins
    assert index.at(3.).id == "overlap"
    assert index.at(4.) is None
    assert index.at(5.).id == "last"
    assert index.at(6.) is None
    document.replace("overlap", text="Human correction")
    index.set_entries(document.edited)
    assert index.at(2.).text == "Human correction"
    document.reset()
    index.set_entries(document.edited)
    assert index.at(2.).text == "Chào cả lớp"
    document.split("first", 1.5)
    index.set_entries(document.edited)
    assert index.at(1.5).text == "" or index.at(1.5).id == "overlap"


def test_stt_result_action_exports_reviewed_text_with_vietnamese(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    app = create_application([])
    panel = STTPanel()
    destination = tmp_path / "review.srt"
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        lambda *args, **kwargs: (str(destination), "SubRip (*.srt)"))
    try:
        panel._show({"kind": "stt", "source": "talk.wav", "duration": 3.,
                     "segments": [{"id": "a", "start": 1., "end": 2.,
                                   "text": "Original"}]})
        assert panel.export_button.isEnabled()
        panel.document.replace("a", text="Tiếng Việt đã sửa")
        panel._export()
        exported = destination.read_text(encoding="utf-8")
        assert "Tiếng Việt đã sửa" in exported and "Original" not in exported
        assert "00:00:01,000 --> 00:00:02,000" in exported
        assert panel.open_folder_button.isVisible() is False or panel.last_export_path == destination
    finally:
        panel.close()
        app.processEvents()


def test_subtitle_toggle_and_live_review_update_in_qt():
    app = create_application([])
    window = build_app()
    try:
        document = _doc()
        window.stt_panel.load_document(document)
        window.video_widget.overlay.set_subtitles(document.edited)
        overlay = window.video_widget.overlay
        overlay.set_position(2.3)
        assert overlay._subtitles.at(2.3).text == "Chào cả lớp"
        document.replace("overlap", text="Cập nhật trực tiếp")
        window._save_project_review()
        assert overlay._subtitles.at(2.3).text == "Cập nhật trực tiếp"
        action = window.actions["subtitles"]
        assert action.isChecked()
        action.trigger()
        assert not action.isChecked() and not overlay._show_subtitles
        action.trigger()
        assert overlay._show_subtitles
    finally:
        window.close()
        app.processEvents()
