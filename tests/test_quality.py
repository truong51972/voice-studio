import pytest
from voice_studio.quality import aggregate, edit_distance, error_counts, evaluate_fixture

def test_wer_cer_keep_vietnamese_tones():
    correct = error_counts("Xin chào bạn", "xin chào bạn.")
    assert correct["word_errors"] == 0
    assert correct["char_errors"] == 0
    missed = error_counts("Xin chào bạn", "xin chao ban")
    assert missed["word_errors"] == 2
    assert missed["char_errors"] > 0

def test_edit_distance_memory_stable_and_empty_reference():
    assert edit_distance([], []) == 0
    assert edit_distance(list("abc"), list("adc")) == 1
    assert edit_distance(["hello", "world"], ["hello"]) == 1
    totals = aggregate([error_counts("", "sound")])
    assert totals["wer"] is None
    assert totals["cer"] is None

def test_evaluate_by_named_media_not_fabricated_numbers():
    out = {"fixture.m4a": {
        "segments": [{"text": "Chào bạn"}], "duration": 12,
    }}
    report = evaluate_fixture(
        [{"source": "fixture.m4a", "reference": "Chào bạn"}], out,
    )
    assert report["aggregate"]["wer"] == 0.0
    assert report["aggregate"]["cer"] == 0.0
    with pytest.raises(KeyError):
        evaluate_fixture([{"source": "not-here.m4a", "reference": "x"}], out)
