"""Project dashboard, contextual STT progress, and persistent clip ordering."""
import json
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from voice_studio.domain.timeline import TimelineClip
from voice_studio.projects import ProjectStore
from voice_studio.ui import build_app, create_application
from voice_studio.ui import project_browser
from voice_studio.ui.project_browser import scan_projects


def test_home_scan_is_read_only_and_reports_invalid_manifests(tmp_path):
    root = tmp_path / ".projects"
    good = root / "opaque-uuid-123"
    bad = root / "broken-uuid-456"
    good.mkdir(parents=True)
    bad.mkdir()
    manifest = good / "project.json"
    manifest.write_text(json.dumps({
        "version": 2, "id": "a", "name": "Conference review",
        "media": [{"id": "m1", "duration": 90}],
        "clips": [{"id": "c1", "media_id": "m1", "source_in": 10, "source_out": 40}],
    }))
    (bad / "project.json").write_text("{broken json")
    before = manifest.read_bytes()
    found = scan_projects(root)
    assert {p.directory for p in found} == {good, bad}
    summary = next(p for p in found if p.directory == good)
    assert summary.name == "Conference review"
    assert summary.source_count == 1
    assert summary.duration == 30
    assert next(p for p in found if p.directory == bad).error
    assert manifest.read_bytes() == before
    assert not (good / "results").exists()  # No ProjectStore side effects.


def test_home_selects_named_projects_and_returns_from_editor(tmp_path, monkeypatch):
    root = tmp_path / ".projects"
    folder = root / "uuid-folder"
    folder.mkdir(parents=True)
    manifest = folder / "project.json"
    manifest.write_text(json.dumps({
        "version": 2, "id": "id123", "name": "Friendly meeting",
        "settings": {}, "media": [], "clips": [], "speakers": [],
        "references": [], "analyses": [], "cluster_mappings": {}, "proposals": [],
    }))
    monkeypatch.setattr(project_browser, "application_directory", lambda: tmp_path)
    app = create_application([])
    window = build_app()
    try:
        browser = window.project_browser
        assert window.pages.currentWidget() is browser
        assert browser.table.rowCount() == 1
        assert browser.table.item(0, 0).text() == "Friendly meeting"
        assert "uuid-folder" not in browser.table.item(0, 0).text()
        browser.table.selectRow(0)
        browser.open_selected()
        assert window.session.project.name == "Friendly meeting"
        assert window.pages.currentIndex() == 1
        window._show_home()
        assert window.pages.currentIndex() == 0
        assert window.session.project is None
        assert browser.table.rowCount() == 1
    finally:
        window.close()
        app.processEvents()


def _workspace_with_sources(tmp_path):
    project = ProjectStore(tmp_path / "test")
    names = ["part-1.wav", "part-2.wav", "part-3.wav"]
    sources = []
    for name in names:
        source = tmp_path / name
        source.write_bytes(b"placeholder")
        sources.append(source)
    project.add(sources)
    for item in project.items:
        item.duration = 10.
    project.save()
    return project


def test_reorder_clip_rows_persists_and_batch_targets_follow_clip_order(tmp_path):
    app = create_application([])
    project = _workspace_with_sources(tmp_path)
    ids = [c.id for c in project.clips]
    media = [c.media_id for c in project.clips]
    window = build_app()
    try:
        window.session.project = project
        window.projects_panel._refresh()
        window._reorder_clips([ids[2], ids[0], ids[1]])
        assert [c.id for c in project.clips] == [ids[2], ids[0], ids[1]]
        assert window.projects_panel.table.item(0, 0).text().startswith("1. part-3.wav")
        assert window._targets(all_sources=True) == [media[2], media[0], media[1]]
        reopened = ProjectStore(project.directory, check_sources=False)
        assert [c.id for c in reopened.clips] == [ids[2], ids[0], ids[1]]
        # Same media may occur twice on a timeline; never infer twice in one batch.
        project.clips.append(TimelineClip("repeated", media[2]))
        assert window._targets(all_sources=True) == [media[2], media[0], media[1]]
        assert window.projects_panel.table.dragDropMode().name == "InternalMove"
    finally:
        window.close()
        app.processEvents()


def test_stt_progress_is_contextual_and_replaces_empty_transcript():
    app = create_application([])
    window = build_app()
    try:
        info = {
            "state": "running", "filename": "very-long-conference-filename.m4a",
            "model": "whisper-large-v3", "device": "cuda", "stage": "Transcribing 420–450",
            "processed_seconds": 420., "total_seconds": 1839.,
            "fraction": .228, "elapsed_seconds": 67., "eta_seconds": 91.,
            "source_index": 1, "source_count": 1,
        }
        window._on_stt_progress(info)
        assert window.stt_progress.parentWidget() is window.stt_panel
        assert window.stt_progress.progress_bar.value() == 228
        assert window.stt_progress.percent.text() == "23%"
        assert "ETA 01:31" in window.stt_progress.detail.text()
        assert window.stt_panel.cancel_button.isHidden()
        assert window.stt_panel.empty_state.isHidden() is False
        assert window.stt_panel.table.isHidden()
        window._status("very-long-conference-filename.m4a · stt · Transcribing 420–450")
        assert "very-long" not in window.preview_status.text()
        window._on_stt_progress({**info, "state": "completed", "fraction": 1.})
        assert window.stt_progress.cancel_button.isHidden()
        assert window.stt_panel.run_button.isEnabled()
    finally:
        window.close()
        app.processEvents()
