import json
import pytest
from voice_studio.transcript import TranscriptDocument, export_text

@pytest.fixture
def document():
    return TranscriptDocument({
        "kind": "stt", "source": "meeting.m4a", "model_id": "whisper-small",
        "segments": [
            {"id": "s1", "start": 1.0, "end": 3.0, "text": "Chao ban", "language": "vi"},
            {"id": "s2", "start": 3.0, "end": 5.0, "text": "Hello", "language": "en"},
        ],
    })

def test_raw_is_immutable_and_edits_are_revertible(document):
    document.replace("s1", text="Chào bạn")
    assert document.edited[0].text == "Chào bạn"
    assert document.raw[0].text == "Chao ban"
    assert document.revision == 1
    document.reset()
    assert document.edited[0].text == "Chao ban"
    assert document.raw[0].text == "Chao ban"

def test_split_merge_and_round_trip(document):
    first, second = document.split("s1", 2.0)
    assert len(document.edited) == 3
    assert document.edited[1].text == ""
    document.replace(second, text="nữa")
    doc_id = document.merge(first, second)
    assert document.edited[0].id == doc_id
    assert document.edited[0].text == "Chao ban nữa"
    restored = TranscriptDocument.restore(json.loads(json.dumps(document.serialize())))
    assert restored.serialize() == document.serialize()
    with pytest.raises(ValueError):
        restored.split(doc_id, 0)

def test_search_export_with_source_and_timestamps(document):
    assert document.find("HELLO") == [1]
    document.replace("s1", text="Chào bạn")
    assert "Chào bạn" in export_text(document, "txt")
    srt = export_text(document, "srt")
    assert "00:00:01,000 --> 00:00:03,000" in srt
    assert "2\n00:00:03,000 --> 00:00:05,000" in srt
    md = export_text(document, "md")
    assert "Source: `meeting.m4a`" in md and "Edited revision: 1" in md
    assert "Model: `whisper-small`" in md
    structured = json.loads(export_text(document, "json"))
    assert structured["raw"]["segments"][0]["text"] == "Chao ban"
    assert structured["edited"][0]["text"] == "Chào bạn"
    with pytest.raises(ValueError):
        export_text(document, "pdf")

def test_validate_adjacent_merge_only(document):
    with pytest.raises(ValueError):
        document.merge("s2", "s1")
    with pytest.raises(KeyError):
        document.replace("unknown", text="anything")

def test_long_transcript_search():
    base = {
        "kind": "stt", "segments": [
            {"id": f"s{i}", "start": float(i), "end": float(i+1),
             "text": f"Segment {i}"} for i in range(1500)
        ]
    }
    doc = TranscriptDocument(base)
    assert len(doc.find("segment")) == 1500
    assert doc.find("segment 1499") == [1499]
