import json
from pathlib import Path
import pytest

from voice_studio.projects import ProjectStore

def _result(source):
    return {"kind": "stt", "source": str(source), "duration": 5,
            "segments": [{"id": "s1", "start": 0., "end": 1., "text": "Chào bạn"}]}

def test_three_files_preserve_order_and_review_after_reopen(tmp_path):
    media = tmp_path / "media"
    media.mkdir()
    paths = []
    for i in range(3):
        path = media / f"talk{i}.m4a"
        path.write_bytes(bytes([i]) * 50)
        paths.append(path)
    folder = tmp_path / "project"
    store = ProjectStore(folder)
    store.add(paths)
    assert len(store.items) == 3
    assert [Path(x.source).name for x in store.items] == [p.name for p in paths]
    opts = {"model_id": "small", "language": "vi"}
    for item in store.items:
        assert store.should_run(item, opts)
        store.begin(item.id, opts)
        store.complete(item.id, _result(item.source))
        assert not store.should_run(item, opts)
    doc = store.review(store.items[0].id)
    doc.replace("s1", text="Đã sửa")
    store.save_review(store.items[0].id, doc)
    reopened = ProjectStore(folder)
    assert reopened.review(reopened.items[0].id).edited[0].text == "Đã sửa"
    combined = reopened.combined_export()
    assert combined.index("talk0") < combined.index("talk1") < combined.index("talk2")
    assert "Đã sửa" in combined
    assert reopened.combined_export("txt").count("==== File") == 3

def test_recover_interrupted_and_retry_without_invalidating_completed(tmp_path):
    media = tmp_path / "talk.wav"
    media.write_bytes(b"audio")
    store = ProjectStore(tmp_path / "project")
    store.add([media])
    item = store.items[0]
    options = {"model_id": "small"}
    store.begin(item.id, options)
    recovered = ProjectStore(store.directory)
    assert recovered.items[0].status == "interrupted"
    assert recovered.should_run(recovered.items[0], options)
    recovered.begin(item.id, options)
    recovered.complete(item.id, _result(media))
    assert not recovered.should_run(recovered.items[0], options)
    assert recovered.should_run(recovered.items[0], {"model_id": "medium"})

def test_source_change_invalidates_cache_and_missing_is_reported(tmp_path):
    source = tmp_path / "meeting.m4a"
    source.write_bytes(b"original")
    project = ProjectStore(tmp_path / "project")
    project.add([source])
    source.write_bytes(b"changed")
    reloaded = ProjectStore(project.directory)
    assert reloaded.items[0].status == "changed"
    with pytest.raises(ValueError):
        reloaded.begin(reloaded.items[0].id, {"model": "small"})
    reloaded.relink(reloaded.items[0].id, source)
    assert reloaded.items[0].status == "pending"
    source.unlink()
    missing = ProjectStore(project.directory)
    assert missing.items[0].status == "missing"


def test_legacy_migration_preserves_backup_results_reviews_and_ids(tmp_path):
    source = tmp_path / "audio.wav"
    source.write_bytes(b"audio")
    store = ProjectStore(tmp_path / "project")
    store.add([source])
    item = store.items[0]
    options = {"model_id": "small"}
    store.begin(item.id, options)
    store.complete(item.id, _result(source))
    doc = store.review(item.id)
    doc.replace("s1", text="Reviewed")
    store.save_review(item.id, doc)
    payload = json.loads(store.manifest.read_text())
    legacy = {"version": 1, "name": "Legacy", "items": payload["media"]}
    for entry in legacy["items"]:
        entry.pop("kind")
    original = json.dumps(legacy, ensure_ascii=False).encode()
    store.manifest.write_bytes(original)

    migrated = ProjectStore(store.directory)
    assert (store.directory / "project.v1.backup.json").read_bytes() == original
    assert json.loads(store.manifest.read_text())["version"] == 2
    assert migrated.items[0].id == item.id
    assert migrated.clips[0].media_id == item.id
    assert not migrated.should_run(migrated.items[0], options)
    assert migrated.review(item.id).edited[0].text == "Reviewed"
    reopened = ProjectStore(store.directory)
    assert reopened.id == migrated.id
    assert reopened.clips == migrated.clips
    assert (store.directory / "project.v1.backup.json").read_bytes() == original


def test_unsupported_version_is_never_rewritten(tmp_path):
    folder = tmp_path / "project"
    folder.mkdir()
    manifest = folder / "project.json"
    payload = b'{"version": 9000, "name": "Future"}'
    manifest.write_bytes(payload)
    with pytest.raises(ValueError, match="Unsupported project manifest version: 9000"):
        ProjectStore(folder)
    assert manifest.read_bytes() == payload
    assert list(folder.iterdir()) == [manifest]


def test_failed_migration_write_keeps_original_and_backup(tmp_path, monkeypatch):
    import voice_studio.projects as projects
    folder = tmp_path / "project"
    folder.mkdir()
    original = b'{"version": 1, "name": "Legacy", "items": []}'
    (folder / "project.json").write_bytes(original)
    original_replace = projects.os.replace
    def fail_replace(source, destination):
        if Path(destination).name == "project.json":
            raise OSError("disk full")
        return original_replace(source, destination)
    monkeypatch.setattr(projects.os, "replace", fail_replace)
    with pytest.raises(OSError, match="disk full"):
        ProjectStore(folder)
    assert (folder / "project.json").read_bytes() == original
    assert (folder / "project.v1.backup.json").read_bytes() == original
    assert not list(folder.glob("*.tmp"))


def test_failed_backup_does_not_publish_partial_backup_or_migrate(tmp_path, monkeypatch):
    import voice_studio.projects as projects
    folder = tmp_path / "project"
    folder.mkdir()
    original = b'{"version": 1, "name": "Legacy", "items": []}'
    (folder / "project.json").write_bytes(original)
    original_replace = projects.os.replace
    def fail_replace(*args):
        raise OSError("backup disk full")
    monkeypatch.setattr(projects.os, "replace", fail_replace)
    with pytest.raises(OSError, match="backup disk full"):
        ProjectStore(folder)
    assert (folder / "project.json").read_bytes() == original
    assert not (folder / "project.v1.backup.json").exists()
    assert not list(folder.glob("*.tmp"))
    monkeypatch.setattr(projects.os, "replace", original_replace)
    ProjectStore(folder)
    assert (folder / "project.v1.backup.json").read_bytes() == original


def test_relink_is_blocked_during_inference(tmp_path):
    source = tmp_path / "source.wav"
    source.write_bytes(b"audio")
    store = ProjectStore(tmp_path / "project")
    store.add([source])
    item = store.items[0]
    store.begin(item.id, {})
    with pytest.raises(ValueError, match="running job"):
        store.relink(item.id, source)
    assert item.status == "running"


def test_reorder_and_trim_keep_source_cache_and_review(tmp_path):
    sources = [tmp_path / "first.wav", tmp_path / "second.wav"]
    for index, path in enumerate(sources):
        path.write_bytes(bytes([index]))
    project = ProjectStore(tmp_path / "project")
    project.add(sources)
    options = {"model_id": "small"}
    for item in project.items:
        project.begin(item.id, options)
        project.complete(item.id, _result(item.source))
    raw = {path.name: path.read_bytes() for path in (project.directory / "results").iterdir()}
    first, second = project.clips
    project.trim_clip(first.id, .5, 3.)
    project.reorder_clips([second.id, first.id])
    restored = ProjectStore(project.directory)
    assert restored.timeline().source_to_project(first.id, 1.) == 5.5
    assert all(not restored.should_run(item, options) for item in restored.items)
    assert raw == {path.name: path.read_bytes() for path in (project.directory / "results").iterdir()}
    report = restored.combined_export("txt")
    assert report.index("second.wav") < report.index("first.wav")
    assert "Source interval: 0.500–3.000s" in report
    with pytest.raises(ValueError):
        restored.trim_clip(first.id, 0., 6.)
    with pytest.raises(ValueError):
        restored.reorder_clips([first.id, first.id])


def test_relink_identical_content_keeps_cache_and_clip_ids(tmp_path):
    source = tmp_path / "original.m4a"
    source.write_bytes(b"same-content")
    project = ProjectStore(tmp_path / "project")
    project.add([source])
    item = project.items[0]
    options = {"model_id": "small"}
    project.begin(item.id, options)
    project.complete(item.id, _result(source))
    clip_id = project.clips[0].id
    moved = tmp_path / "moved.m4a"
    source.rename(moved)
    reopened = ProjectStore(project.directory)
    assert reopened.items[0].status == "missing"
    reopened.relink(item.id, moved)
    assert not reopened.should_run(reopened.items[0], options)
    assert reopened.clips[0].id == clip_id
    assert reopened.items[0].source == str(moved)
    assert reopened.review(item.id).raw_metadata["source"] == str(source)


def test_failed_multi_import_has_no_partial_items(tmp_path):
    source = tmp_path / "exists.wav"
    source.write_bytes(b"audio")
    store = ProjectStore(tmp_path / "project")
    with pytest.raises(FileNotFoundError):
        store.add([source, tmp_path / "missing.wav"])
    assert store.items == []
    assert store.clips == []
    assert ProjectStore(store.directory).items == []
