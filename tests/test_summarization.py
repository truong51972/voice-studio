from voice_studio.summarization import summarize, summary_markdown
from voice_studio.transcript import TranscriptDocument

def _doc():
    return TranscriptDocument({
        "kind": "stt", "source": "meeting.m4a",
        "segments": [
            {"id": "s1", "start": 1, "end": 3, "text": "We should release the report."},
            {"id": "s2", "start": 3, "end": 6, "text": "Tôi sẽ gửi bản nháp vào thứ hai."},
        ]
    })

def test_ai_summary_requires_actual_source_segments_and_does_not_rewrite_raw():
    document = _doc()
    def fake(prompt, model):
        assert "s1" in prompt and model == "local-model"
        return {"items": [
            {"section": "Topics", "text": "Discussed reporting.", "source_ids": ["s1"]},
            {"section": "Action items", "text": "Invented item", "source_ids": ["fake"]},
            {"section": "Action items", "text": "Unsupported", "source_ids": []},
        ]}
    result = summarize(document, model="local-model", requester=fake)
    assert len(result["items"]) == 1
    assert result["items"][0]["source_time_ranges"] == [[1, 3]]
    assert "AI draft" in summary_markdown(result)
    assert "meeting.m4a" in summary_markdown(result)
    assert document.raw[0].text == "We should release the report."

def test_no_network_without_explicit_requester_call():
    document = _doc()
    assert document.raw_metadata["source"] == "meeting.m4a"
    # Construction never invokes the local model.
