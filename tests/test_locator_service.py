from voice_studio import service


def test_ui_independent_locator_service_preserves_selection(monkeypatch):
    calls = []

    def fake_compute(refs, target_audio, target_video, threshold, *, profile_key):
        calls.append((refs, target_audio, target_video, threshold, profile_key))
        return "bundle"

    monkeypatch.setattr(service, "_compute_analysis", fake_compute)
    worker = service.LocatorService()
    bundle, threshold = worker.analyze(
        [("Speaker 1", "ref.wav")], "recording.wav", None, None,
        profile_key="fast",
    )
    assert bundle == "bundle"
    assert threshold == 0.60
    assert calls == [([("Speaker 1", "ref.wav")], "recording.wav", None, 0.6, "fast")]


def test_legacy_audio_aliases_are_compatible():
    from voice_studio.audio import AudioInput, GradioAudio, prepare_audio, prepare_gradio_audio
    assert AudioInput == GradioAudio
    assert callable(prepare_audio)
    assert callable(prepare_gradio_audio)
