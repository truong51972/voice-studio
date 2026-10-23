"""Regression tests for clip drag/drop, cached timeline mapping and persistence."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView

from voice_studio.projects import ProjectStore
from voice_studio.ui import build_app, create_application
from voice_studio.ui.panels.projects import ClipOrderTable


def test_reorder_helper_uses_clip_identity_and_insert_position():
    ids = ["one", "two", "three", "four"]
    assert ClipOrderTable.reordered_ids(ids, 0, 4) == ["two", "three", "four", "one"]
    assert ClipOrderTable.reordered_ids(ids, 3, 0) == ["four", "one", "two", "three"]
    assert ClipOrderTable.reordered_ids(ids, 1, 2) == ids
    assert ids == ["one", "two", "three", "four"]


def test_reordering_warm_timeline_never_reloads_source_results(tmp_path, monkeypatch):
    app = create_application([])
    project = ProjectStore(tmp_path / "project")
    for i in range(3):
        source = tmp_path / f"part{i}.wav"
        source.write_bytes(b"placeholder")
        project.add([source])
    for item in project.items:
        item.duration = 10.
    project.save()
    ids = [clip.id for clip in project.clips]
    window = build_app()
    try:
        window.session.project = project
        window.projects_panel._refresh()
        window._clip_id = ids[1]
        sources = [{"clip": clip, "name": "source", "duration": 10., "peaks": []}
                   for clip in project.clips]
        annotations = [
            {"clip_id": ids[0], "start": 2., "end": 3., "lane": "Transcript",
             "text": "first", "media_id": project.clips[0].media_id},
            {"clip_id": ids[2], "start": 22., "end": 23., "lane": "Transcript",
             "text": "third", "media_id": project.clips[2].media_id},
        ]
        window.timeline.set_project_data(project.timeline(), sources, annotations)
        def full_reload_forbidden():
            raise AssertionError("Reorder must not reload transcripts or waveforms")
        monkeypatch.setattr(window, "_render_timeline", full_reload_forbidden)
        window._reorder_clips([ids[2], ids[0], ids[1]])
        assert [c.id for c in project.clips] == [ids[2], ids[0], ids[1]]
        assert [s["clip"].id for s in window.timeline._sources] == [ids[2], ids[0], ids[1]]
        assert {a["clip_id"]: (a["start"], a["end"])
                for a in window.timeline._annotations} == {
                    ids[0]: (12., 13.), ids[2]: (2., 3.)}
        assert window._clip_id == ids[1]  # Keep the current clip's identity.
        assert window.projects_panel.table.item(0, 0).data(Qt.ItemDataRole.UserRole) == ids[2]
        reopened = ProjectStore(project.directory, check_sources=False)
        assert [c.id for c in reopened.clips] == [ids[2], ids[0], ids[1]]
    finally:
        window.close()
        app.processEvents()


def test_drop_reorders_without_emitting_synchronously(tmp_path, monkeypatch):
    """The view must exit dropEvent before rebuilding its own table."""
    from PySide6.QtCore import QPointF

    app = create_application([])
    table = ClipOrderTable(3, 1)
    try:
        from PySide6.QtWidgets import QTableWidgetItem
        for i in range(3):
            cell = QTableWidgetItem(f"Source {i}")
            cell.setData(Qt.ItemDataRole.UserRole, str(i))
            table.setItem(i, 0, cell)
        table.selectRow(0)
        table.show()
        app.processEvents()
        monkeypatch.setattr(table, "dropIndicatorPosition",
                            lambda: QAbstractItemView.DropIndicatorPosition.BelowItem)
        target = table.visualItemRect(table.item(2, 0))
        class Drop:
            accepted = False
            def source(self):
                return table
            def position(self):
                return QPointF(target.center())
            def acceptProposedAction(self):
                self.accepted = True
            def ignore(self):
                pass
        event = Drop()
        captured = []
        table.reorderRequested.connect(lambda ids: captured.append(ids))
        table.dropEvent(event)
        assert event.accepted
        assert captured == []  # Queued after Qt finishes its drag lifecycle.
        app.processEvents()
        assert captured == [["1", "2", "0"]]
    finally:
        table.close()
