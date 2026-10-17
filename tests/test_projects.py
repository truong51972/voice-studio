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
