import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import soundfile as sf
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMainWindow, QScrollArea

from voice_studio.audio import prepare_gradio_audio
from voice_studio.localization import MatchSegment
from voice_studio.pipeline import AnalysisBundle, SpeakerResult
from voice_studio.profiles import DEFAULT_PROFILE_KEY, INFERENCE_PROFILES
from voice_studio.ui import (
    DEFAULT_REFERENCE_SPEAKERS,
    MAX_REFERENCE_SPEAKERS,
    build_app,
    create_application,
)


def test_reference_speaker_defaults_and_limit():
    assert DEFAULT_REFERENCE_SPEAKERS == 1
    assert MAX_REFERENCE_SPEAKERS == 3


def test_prepare_audio_filepath_contract_is_preserved(tmp_path: Path):
    path = tmp_path / "ref.wav"
    sf.write(path, np.zeros(16_000, dtype=np.float32), 16_000)
    samples = prepare_gradio_audio(str(path))
    assert samples.dtype == np.float32
    assert samples.shape == (16_000,)


def test_workspace_uses_editor_splitters_without_page_scroll():
    app = create_application([])
    window = build_app()
    try:
        assert isinstance(window, QMainWindow)
        assert window.root_splitter.orientation() == Qt.Orientation.Vertical
        assert window.workspace_splitter.orientation() == Qt.Orientation.Horizontal
        assert window.analysis_page.findChildren(QScrollArea) == []
        assert window.pages.currentIndex() == 0
        assert window.speakers_panel.mode.currentIndex() == 0
        assert window.stt_panel._manager is None
        assert window.diarization_panel._manager is None
        assert window.summary_panel._manager is None
        assert window.segment_table.columnCount() == 4
        assert window.profile.currentData() == DEFAULT_PROFILE_KEY
        assert not window.windowIcon().isNull()
    finally:
        window.close()
        app.processEvents()


def test_manual_reference_is_a_source_selection_without_enrollment_uploads():
    app = create_application([])
    window = build_app()
    try:
        from PySide6.QtWidgets import QPushButton
        reference = window.speakers_panel.reference
        assert reference.start.value() == 0
        assert reference.end.value() == 0
        assert reference.source.count() == 0
        assert reference.speaker.count() == 0
        assert not reference.clean.isChecked()
        labels = [button.text().lower() for button in reference.findChildren(QPushButton)]
        assert not any('record' in label or 'upload' in label or 'file' in label for label in labels)
        assert 'preview interval' in labels
        window._manual_selection()
        assert window.speakers_panel.mode.currentIndex() == 1
    finally:
        window.close()
        app.processEvents()


def test_preview_overlay_tracks_active_speaker_segment():
    app = create_application([])
    window = build_app()
    try:
        segment = MatchSegment(start=1.0, end=3.0, avg_score=0.72, max_score=0.84)
        result = SpeakerResult(
            key="spk_01",
            name="Học sinh A",
            scores=[],
            segments=[segment],
            matched_duration=2.0,
            coverage=20.0,
            max_score=0.84,
        )
        bundle = AnalysisBundle(
            target=np.zeros(16_000, dtype=np.float32),
            media_kind="video",
            duration=10.0,
            results=[result],
            scores_by_name={"Học sinh A": []},
            segments_by_name={"Học sinh A": [segment]},
        )
        window.video_widget.overlay.set_bundle(bundle)
        window.video_widget.overlay.set_position(2.0)
        active = window.video_widget.overlay._active_results()
        assert len(active) == 1
        assert active[0][0].name == "Học sinh A"
        window.video_widget.overlay.set_position(5.0)
        assert window.video_widget.overlay._active_results() == []
    finally:
        window.close()
        app.processEvents()


def test_profile_selector_applies_profile_default_threshold():
    app = create_application([])
    window = build_app()
    try:
        profile = INFERENCE_PROFILES["accurate"]
        index = window.profile.findData(profile.key)
        assert index >= 0
        window.profile.setCurrentIndex(index)
        assert window.threshold.value() == profile.default_threshold
        assert profile.description in window.profile_help.text()
    finally:
        window.close()
        app.processEvents()


def test_src_layout_exposes_installed_desktop_entrypoint():
    root = Path(__file__).parents[1]
    source = (root / "src" / "voice_studio" / "app.py").read_text(encoding="utf-8")
    module_entry = (root / "src" / "voice_studio" / "__main__.py").read_text(encoding="utf-8")
    project = (root / "pyproject.toml").read_text(encoding="utf-8")

    assert not (root / "app.py").exists()
    assert "app.launch" not in source
    assert "create_application" in source
    assert "qt_app.exec()" in source
    assert "from .app import main" in module_entry
    assert '[build-system]' in project
    assert 'build-backend = "hatchling.build"' in project
    assert '[project.scripts]' in project
    assert 'voice-studio = "voice_studio.app:main"' in project
    assert 'start = "voice-studio"' in project
    assert 'desktop = "voice-studio"' in project
    assert 'pythonpath = ["src"]' not in project
    assert "PySide6" in project
    assert '"gradio==' not in project
