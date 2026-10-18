"""Standards-based cue interoperability and legacy review migration."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from voice_studio.subtitle_formats import SubtitleCue, parse_subtitles, serialize_subtitles
from voice_studio.transcript import TranscriptDocument, export_text
from voice_studio.projects import ProjectStore
from voice_studio.ui import create_application
from voice_studio.ui.panels.stt import STTPanel


def test_webvtt_standard_roundtrip_multiline_utf8_and_gaps():
    cues = [
        SubtitleCue("first", 1.25, 3.75, "Xin chào & một ngày tốt lành"),
        SubtitleCue("second", 4., 6., "Hello\nworld <3"),
    ]
    content = serialize_subtitles(cues)
    assert content.startswith("WEBVTT\n\n")
    assert "00:00:01.250 --> 00:00:03.750" in content
    assert "Xin chào &amp; một ngày tốt lành" in content
    assert parse_subtitles(content.replace("\n", "\r\n"), "vtt") == cues
    assert parse_subtitles("\ufeff" + content, "vtt") == cues
    assert len(parse_subtitles("WEBVTT\n\nNOTE auto-generated\nignored\n\n" +
                               content.split("\n\n", 1)[1])) == 2


def test_subrip_import_has_standard_timecodes_and_stable_order():
    content = ("1\r\n00:00:01,100 --> 00:00:02,200\r\nXin chào\r\n\r\n"
               "2\r\n00:00:02,200 --> 00:00:03,000\r\nBonjour\r\n")
    cues = parse_subtitles(content, "srt")
    assert len(cues) == 2
    assert cues[0].text == "Xin chào"
    assert cues[1].start == 2.2
    assert serialize_subtitles(cues, "srt").count("-->") == 2


@pytest.mark.parametrize("source,kind", [
    ("WEBVTT\n\nfirst\n00:00:03.000 --> 00:00:02.000\nBad\n", "vtt"),
    ("WEBVTT\n\nfirst\n00:00:00.000 --> 00:00:01.000\nOkay\n\n"
     "first\n00:00:01.000 --> 00:00:02.000\nDuplicate\n", "vtt"),
    ("WEBVTT\n\nfirst\n00:00:AA.000 --> 00:00:01.000\nBad\n", "vtt"),
    ("1\n00:00:00,000 --> 00:00:00,000\nBad\n", "srt"),
])
def test_invalid_subtitles_are_rejected(source, kind):
    with pytest.raises(ValueError):
        parse_subtitles(source, kind)


def _project_with_stt(tmp_path: Path):
    source = tmp_path / "recording.m4a"
    source.write_bytes(b"stable dummy content")
    project = ProjectStore(tmp_path / "project")
    project.add([source])
    item = project.items[0]
    item.duration = 8.
    record = project.queue_analysis(item.id, "stt", {})
    project.finish_analysis(record, {
        "kind": "stt", "source": str(source), "duration": 8.,
        "segments": [
            {"id": "a", "start": .5, "end": 2., "text": "unreviewed"},
            {"id": "b", "start": 2.5, "end": 4., "text": "raw"},
        ],
    })
    return project, item


def test_review_vtt_is_portable_source_legacy_json_is_preserved(tmp_path):
    project, item = _project_with_stt(tmp_path)
    doc = project.review(item.id)
    doc.replace("a", text="Đã sửa")
    project.save_review(item.id, doc)
    path = project._review_path(item).with_suffix(".vtt")
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert "WEBVTT" in text and "Đã sửa" in text
    assert json.loads(project._review_path(item).read_text())["raw"]["segments"][0]["text"] == "unreviewed"

    # An external subtitle editor modifies the standard .vtt; reopened review
    # must take cue text and timing from the file rather than stale JSON.
    external = [SubtitleCue("a", 1., 2., "Từ tệp VTT"), SubtitleCue("b", 2.5, 4., "raw")]
    path.write_text(serialize_subtitles(external), encoding="utf-8")
    reopened = ProjectStore(project.directory)
    reviewed = reopened.review(item.id)
    assert reviewed.edited[0].text == "Từ tệp VTT"
    assert reviewed.edited[0].start == 1.
    assert reviewed.raw[0].text == "unreviewed"
    assert reviewed.edited[1].text == "raw"


def test_legacy_review_json_only_loads_and_upgrades_on_save(tmp_path):
    project, item = _project_with_stt(tmp_path)
    document = project.review(item.id)
    document.replace("b", text="Legacy JSON edit")
    path = project._review_path(item)
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(document.serialize()), encoding="utf-8")
    assert not path.with_suffix(".vtt").exists()
    restored = project.review(item.id)
    assert restored.edited[1].text == "Legacy JSON edit"
    project.save_review(item.id, restored)
    assert parse_subtitles(path.with_suffix(".vtt").read_text(), "vtt")[1].text == "Legacy JSON edit"


def test_empty_split_entries_survive_vtt_project_roundtrip(tmp_path):
    project, item = _project_with_stt(tmp_path)
    document = project.review(item.id)
    document.split("a", 1.5)
    project.save_review(item.id, document)
    reopened = project.review(item.id)
    assert len(reopened.edited) == 3
    assert reopened.edited[1].text == ""


def test_vtt_selected_export_keeps_only_reviewed_cues():
    doc = TranscriptDocument({"kind": "stt", "source": "recording.wav", "segments": [
        {"id": "a", "start": 0., "end": 1., "text": "outside"},
        {"id": "b", "start": 1., "end": 2., "text": "Xin chào"},
    ]})
    doc.replace("b", text="Chào tất cả")
    exported = export_text(doc, "vtt", source_range=(1., 2.))
    assert exported.startswith("WEBVTT\n\n")
    assert [cue.text for cue in parse_subtitles(exported, "vtt")] == ["Chào tất cả"]


def test_gui_import_vtt_uses_standard_cues_without_touching_raw(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    app = create_application([])
    panel = STTPanel()
    path = tmp_path / "example.vtt"
    path.write_text(serialize_subtitles([SubtitleCue("a", 1., 2., "Đã chỉnh")]), encoding="utf-8")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args, **kwargs: (str(path), ""))
    try:
        panel._show({"kind": "stt", "source": "recording.m4a", "duration": 5.,
                     "segments": [{"id": "a", "start": 1., "end": 2., "text": "Raw"}]})
        panel._import_subtitles()
        assert panel.document.edited[0].text == "Đã chỉnh"
        assert panel.document.raw[0].text == "Raw"
    finally:
        panel.close()
        app.processEvents()
