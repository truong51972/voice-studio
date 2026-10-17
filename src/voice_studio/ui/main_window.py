from __future__ import annotations

"""Single media player and main Qt window; module-independent task panels."""

import os
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Slot, QTimer, QEvent, QSettings
from PySide6.QtGui import QIcon, QAction, QKeySequence
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (QApplication, QComboBox, QFileDialog, QFrame,
                               QHBoxLayout, QLabel, QMainWindow, QMessageBox,
                               QPushButton, QSlider, QSplitter, QTabWidget,
                               QTableWidgetItem, QTextBrowser, QVBoxLayout, QWidget, QDialog, QInputDialog, QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox, QMenu, QToolButton)

from ..pipeline import AnalysisBundle
from ..profiles import get_inference_profile
from .model_manager import ModelManagerDialog
from .actions import EditorActionsMixin
from .panels.locator import LocatorPanelsMixin
from .panels.stt import STTPanel
from .panels.projects import ProjectsPanel
from .panels.diarization import DiarizationPanel
from .panels.summary import SummaryPanel
from .resources import _resource_path
from .theme import APP_STYLESHEET
from .timecode import _fmt_time, _parse_timecode, milliseconds_to_seconds, seconds_to_milliseconds
from .widgets.media_player import PreviewVideoWidget
from .widgets.timeline import EditorTimelineWidget
from .workers import AnalysisWorker

class MainWindow(EditorActionsMixin, LocatorPanelsMixin, QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Voice Studio · Editor")
        self.resize(1380, 860)
        self.setMinimumSize(1080, 700)
        self.setStyleSheet(APP_STYLESHEET)

        icon_path = _resource_path("voice-studio.png")
        if icon_path.is_file():
            self.setWindowIcon(QIcon(str(icon_path)))

        self._target_path: str | None = None
        self._worker: AnalysisWorker | None = None
        self._bundle: AnalysisBundle | None = None

        self._player = QMediaPlayer(self)
        self._audio_output = QAudioOutput(self)
        self._player.setAudioOutput(self._audio_output)

        self.analysis_page = self._build_analysis_tab()
        self.setCentralWidget(self.analysis_page)
        self._build_actions()
        self._state_timer = QTimer(self)
        self._state_timer.setInterval(150)
        self._state_timer.timeout.connect(self._update_actions)
        self._state_timer.start()
        self.stt_panel.modelsRequested.connect(self._open_models)
        self.diarization_panel.modelsRequested.connect(self._open_models)
        self.projects_panel.projectChanged.connect(self._update_actions)
        self.stt_panel.resultReady.connect(self._store_stt_result)
        self._restore_layout()
        self._update_actions()

    def _build_analysis_tab(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        toolbar = QFrame()
        toolbar.setObjectName("toolbar")
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(10, 7, 10, 7)

        title = QLabel("<b>Voice Studio</b>")
        title.setStyleSheet("font-size: 16px;")
        self.target_mode = QComboBox()
        self.target_mode.addItem("🎬 Video", "video")
        self.target_mode.addItem("🎵 Audio", "audio")
        choose_target = QPushButton("Open target")
        choose_target.clicked.connect(self._choose_target)
        self.target_label = QLabel("No media")
        self.target_label.setStyleSheet("color: #9da4ae;")

        self.models_button = QPushButton("Models")
        self.models_button.clicked.connect(self._open_models)
        self.models_button.hide()
        choose_target.hide()
        self.target_mode.hide()
        self.cancel_button = QToolButton()
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._cancel_analysis)
        self.analyze_button = QToolButton()
        self.analyze_button.setObjectName("primaryButton")
        self.analyze_button.clicked.connect(self._start_analysis)

        toolbar_layout.addWidget(title)
        toolbar_layout.addSpacing(14)
        toolbar_layout.addWidget(self.target_label, 1)
        toolbar_layout.addWidget(self.analyze_button)
        toolbar_layout.addWidget(self.cancel_button)
        root.addWidget(toolbar)

        self.root_splitter = QSplitter(Qt.Orientation.Vertical)
        self.root_splitter.setChildrenCollapsible(False)
        self.workspace_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.workspace_splitter.setChildrenCollapsible(False)

        preview_panel = QFrame()
        preview_panel.setObjectName("panel")
        preview_layout = QVBoxLayout(preview_panel)
        preview_layout.setContentsMargins(8, 8, 8, 8)
        preview_layout.setSpacing(6)

        preview_header = QHBoxLayout()
        preview_header.addWidget(QLabel("<b>Preview</b>"))
        self.preview_status = QLabel("Ready")
        self.preview_status.setStyleSheet("color: #8e96a2;")
        preview_header.addStretch(1)
        preview_header.addWidget(self.preview_status)
        preview_layout.addLayout(preview_header)

        self.video_widget = PreviewVideoWidget()
        self.video_widget.setMinimumHeight(300)
        self._player.setVideoOutput(self.video_widget)
        preview_layout.addWidget(self.video_widget, 1)

        transport = QHBoxLayout()
        self.play_button = QPushButton("▶")
        self.play_button.setFixedWidth(42)
        self.play_button.clicked.connect(self._toggle_playback)
        self.time_label = QLabel("0.0s / 0.0s")
        self.time_label.setMinimumWidth(112)
        self.position_slider = QSlider(Qt.Orientation.Horizontal)
        self.position_slider.setRange(0, 0)
        self.position_slider.sliderMoved.connect(self._player.setPosition)
        transport.addWidget(self.play_button)
        transport.addWidget(self.time_label)
        transport.addWidget(self.position_slider, 1)
        preview_layout.addLayout(transport)

        self.inspector_tabs = QTabWidget()
        self.inspector_tabs.setMinimumWidth(340)
        self.inspector_tabs.setMaximumWidth(460)
        self.speakers_page = self._build_speakers_panel()
        self.analysis_settings_page = self._build_analysis_panel()
        self.results_page = self._build_segments_panel()
        self.inspector_tabs.addTab(self.speakers_page, "Speakers")
        self.stt_panel = STTPanel(self)
        self.stt_panel.seekRequested.connect(self._seek_to_seconds)
        self.inspector_tabs.addTab(self.stt_panel, "STT")
        self.projects_panel = ProjectsPanel(self.stt_panel, self)
        self.projects_panel.openRequested.connect(self._open_project_media)

        self.diarization_panel = DiarizationPanel(self)
        self.diarization_panel.seekRequested.connect(self._seek_to_seconds)
        self.diarization_panel.turnsReady.connect(self.stt_panel.apply_diarization)

        self.summary_panel = SummaryPanel(self.stt_panel, self)
        self.inspector_tabs.addTab(self.results_page, "Results")
        self.analysis_settings_page.hide()
        self.diarization_panel.hide()
        self.summary_panel.hide()
        self.projects_panel.setMinimumWidth(235)
        self.projects_panel.setMaximumWidth(380)
        self.workspace_splitter.addWidget(self.projects_panel)
        self.stt_panel.documentChanged.connect(self._save_project_review)

        self.workspace_splitter.addWidget(preview_panel)
        self.workspace_splitter.addWidget(self.inspector_tabs)
        self.workspace_splitter.setStretchFactor(0, 0)
        self.workspace_splitter.setStretchFactor(1, 1)
        self.workspace_splitter.setStretchFactor(2, 0)
        self.workspace_splitter.setSizes([260, 760, 350])

        timeline_panel = QFrame()
        timeline_panel.setObjectName("panel")
        timeline_layout = QVBoxLayout(timeline_panel)
        timeline_layout.setContentsMargins(8, 7, 8, 8)
        timeline_layout.setSpacing(4)

        timeline_header = QHBoxLayout()
        timeline_header.addWidget(QLabel("<b>Speaker timeline</b>"))
        self.summary_label = QLabel("File → Import Media to begin · timeline uses source-local time.")
        self.summary_label.setStyleSheet("color: #9da4ae;")
        timeline_header.addSpacing(12)
        timeline_header.addWidget(self.summary_label, 1)
        timeline_header.addWidget(QLabel("Click timeline to seek"))
        timeline_layout.addLayout(timeline_header)

        self.timeline = EditorTimelineWidget()
        self.timeline.seekRequested.connect(self._seek_to_seconds)
        timeline_layout.addWidget(self.timeline, 1)

        self.root_splitter.addWidget(self.workspace_splitter)
        self.root_splitter.addWidget(timeline_panel)
        self.root_splitter.setStretchFactor(0, 1)
        self.root_splitter.setStretchFactor(1, 0)
        self.root_splitter.setSizes([585, 235])
        root.addWidget(self.root_splitter, 1)

        self._player.positionChanged.connect(self._on_player_position)
        self._player.durationChanged.connect(self._on_player_duration)
        self._player.playbackStateChanged.connect(self._on_playback_state)
        return page

    def _build_help_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        browser = QTextBrowser()
        browser.setHtml(
            """
            <h2>Voice Studio · Known-speaker Locator</h2>
            <p>Mở audio/video trong Workspace, đăng ký 1–3 mẫu giọng đã biết,
            chọn profile CAM++ hoặc ERes2NetV2 rồi bấm Analyze.</p>
            <p>Nhấp timeline hoặc bảng Segments để phát từ vị trí tương ứng.
            Độ tương đồng không phải xác suất xác minh danh tính.</p>
            <p>File → New/Open creates or opens a portable project. Import Media adds sources.
            Process runs transcription, speaker matching, local diarization or summaries.
            Settings → Models installs, imports, verifies and tests model readiness.</p>
            <p>Help → Shortcuts lists keyboard commands. Local summaries use an explicitly selected localhost Ollama model.</p>
            """
        )
        layout.addWidget(browser)
        return page

    def _build_privacy_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        browser = QTextBrowser()
        browser.setHtml(
            """
            <h2>Hướng dẫn & quyền riêng tư</h2>
            <ol>
              <li>Open video/audio target.</li>
              <li>Đặt tên và upload/record 3–5 giây giọng rõ cho từng speaker.</li>
              <li>Chọn profile Nhanh hoặc Chính xác.</li>
              <li>Analyze để sinh speaker clips trên timeline.</li>
              <li>Scrub/click timeline để review; speaker đang match sẽ hiện trực tiếp trên preview.</li>
            </ol>
            <p>Chỉ thu âm/video khi người tham gia và giáo viên/phụ huynh đã đồng ý theo quy định áp dụng.</p>
            <p>Matching là tín hiệu hỗ trợ tìm đoạn cần xem lại, không phải xác nhận danh tính tuyệt đối.</p>
            <p>Audio/video được xử lý cục bộ; ứng dụng không cần gửi media lên dịch vụ speech-to-text hoặc cloud AI.</p>
            """
        )
        layout.addWidget(browser)
        return page

    def _open_models(self, model_id=None):
        if not isinstance(model_id, str):
            model_id = None
        dialog = ModelManagerDialog(self, model_id=model_id)
        dialog.modelsChanged.connect(self.stt_panel.refresh_models)
        dialog.modelsChanged.connect(self.diarization_panel.refresh_models)
        dialog.exec()

    @Slot(str, object)
    def _open_project_media(self, source: str, document: object) -> None:
        self._target_path = source
        self.target_label.setText(Path(source).name)
        self.stt_panel.set_media(source)
        self.diarization_panel.set_media(source)
        self.summary_panel.reset()
        if document is not None:
            self.stt_panel.load_document(document)
        self._player.setSource(QUrl.fromLocalFile(source))
        self._bundle = None
        self.timeline.set_bundle(None)
        self.video_widget.overlay.set_bundle(None)
        self.segment_table.setRowCount(0)

    @Slot()
    def _save_project_review(self) -> None:
        self.projects_panel.save_active_review(self.stt_panel.document)

    @Slot()
    def _choose_target(self) -> None:
        is_video = self.target_mode.currentData() == "video"
        file_filter = (
            "Video (*.mp4 *.mov *.mkv *.avi *.webm);;Tất cả file (*)"
            if is_video
            else "Audio (*.wav *.flac *.ogg *.mp3 *.m4a);;Tất cả file (*)"
        )
        path, _ = QFileDialog.getOpenFileName(
            self, "Chọn target media", "", file_filter
        )
        if not path:
            return

        self._target_path = path
        self.stt_panel.set_media(path)
        self.diarization_panel.set_media(path)
        self.summary_panel.reset()
        self._bundle = None
        self.target_label.setText(Path(path).name)
        self.preview_status.setText("Media loaded")
        self.summary_label.setText("Ready to Analyze.")
        self.timeline.set_bundle(None)
        self.video_widget.overlay.set_bundle(None)
        self.similarity_plot.set_bundle(None, self.threshold.value())
        self.segment_table.setRowCount(0)
        self._player.setSource(QUrl.fromLocalFile(path))

    @Slot()
    def _toggle_playback(self) -> None:
        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()
        else:
            self._player.play()

    @Slot()
    def _start_analysis(self) -> None:
        if self._worker and self._worker.isRunning():
            return
        if not self._target_path:
            QMessageBox.information(self, "Chưa có target", "Hãy open video/audio target trước.")
            return

        from ..model_catalog import descriptors
        from ..model_service import ModelService
        model = next(m for m in descriptors("locator") if m.profile_key == self.profile.currentData())
        errors = ModelService().preflight(model)
        if errors:
            self.preview_status.setText("; ".join(errors))
            self._open_models(model.id)
            return
        references = [reference.value() for reference in self.reference_inputs]
        is_video = Path(self._target_path).suffix.lower() in (".mp4", ".mov", ".mkv", ".avi", ".webm")
        target_audio = None if is_video else self._target_path
        target_video = self._target_path if is_video else None
        threshold = self.threshold.value()
        profile_key = str(self.profile.currentData())

        self.analyze_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.analyze_button.setText("Analyzing…")
        self.preview_status.setText("Analyzing speaker tracks…")
        self.summary_label.setText("Embedding target windows and matching references…")

        self._worker = AnalysisWorker(
            references,
            target_audio,
            target_video,
            threshold,
            self.scenario.currentText(),
            profile_key,
            parent=self,
        )
        self._worker.completed.connect(self._analysis_complete)
        self._worker.failed.connect(self._analysis_failed)
        self._worker.progress.connect(self.preview_status.setText)
        self._worker.finished.connect(self._analysis_finished)
        self._worker.start()

    @Slot()
    def _cancel_analysis(self) -> None:
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self.preview_status.setText("Analysis cancelled")
            self.summary_label.setText("Cancelled; no partial results kept.")

    @Slot(object)
    def _analysis_complete(self, payload: object) -> None:
        bundle, resolved_threshold, scenario, profile_key = payload
        self._bundle = bundle
        detected = sum(1 for result in bundle.results if result.segments)
        total_segments = sum(len(result.segments) for result in bundle.results)
        profile = get_inference_profile(profile_key)

        self.summary_label.setText(
            f"{detected}/{len(bundle.results)} speakers · {total_segments} clips · "
            f"{profile.label} · threshold {resolved_threshold:.2f}"
        )
        self.preview_status.setText(f"Analysis ready · {scenario}")
        self.timeline.set_bundle(bundle)
        self.video_widget.overlay.set_bundle(bundle)
        self.similarity_plot.set_bundle(bundle, resolved_threshold)
        self._populate_segments(bundle)

    @Slot(str)
    def _analysis_failed(self, message: str) -> None:
        self.preview_status.setText("Analysis failed")
        self.summary_label.setText("Không thể chạy model. Kiểm tra target/reference audio.")
        QMessageBox.warning(self, "Không thể phân tích", message)

    @Slot()
    def _analysis_finished(self) -> None:
        self.analyze_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.analyze_button.setText("Analyze")

    def _populate_segments(self, bundle: AnalysisBundle) -> None:
        rows = []
        for result in bundle.results:
            for segment in result.segments:
                rows.append(
                    [
                        result.name,
                        _fmt_time(segment.start),
                        _fmt_time(segment.end),
                        f"{segment.max_score:.3f}",
                    ]
                )

        self.segment_table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            for column_index, value in enumerate(row):
                self.segment_table.setItem(
                    row_index, column_index, QTableWidgetItem(value)
                )

    @Slot(int)
    def _on_player_position(self, position_ms: int) -> None:
        seconds = milliseconds_to_seconds(position_ms)
        self.position_slider.blockSignals(True)
        self.position_slider.setValue(position_ms)
        self.position_slider.blockSignals(False)
        duration = max(0.0, self._player.duration() / 1000.0)
        self.time_label.setText(f"{_fmt_time(seconds)} / {_fmt_time(duration)}")
        self.timeline.set_position_seconds(seconds)
        self.video_widget.overlay.set_position(seconds)
        self.stt_panel.set_playhead(seconds)

    @Slot(int)
    def _on_player_duration(self, duration_ms: int) -> None:
        self.position_slider.setRange(0, max(0, duration_ms))
        self.timeline.set_duration_seconds(milliseconds_to_seconds(duration_ms))

    @Slot(object)
    def _on_playback_state(self, state: object) -> None:
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        self.play_button.setText("⏸" if playing else "▶")

    @Slot(float)
    def _seek_to_seconds(self, seconds: float) -> None:
        self._player.setPosition(seconds_to_milliseconds(seconds))
        self._player.pause()

    @Slot(int, int)
    def _seek_segment(self, row: int, _column: int) -> None:
        item = self.segment_table.item(row, 1)
        if item is None:
            return
        try:
            seconds = _parse_timecode(item.text())
        except ValueError:
            return
        self._seek_to_seconds(seconds)

    def closeEvent(self, event):
        self._save_layout()
        self._state_timer.stop()
        self.projects_panel.cancel()
        self.stt_panel.cancel()
        self.stt_panel._manager.close()
        self.projects_panel._timer.stop()
        self.projects_panel._manager.close()
        self.diarization_panel._manager.close()
        self.summary_panel._manager.close()
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
        super().closeEvent(event)


def create_application(argv: list[str] | None = None) -> QApplication:
    if sys.platform == "linux":
        # Avoid Qt's PipeWire crash when client.conf is missing (e.g. WSLg).
        os.environ.setdefault("QT_AUDIO_BACKEND", "pulseaudio")
    existing = QApplication.instance()
    if existing is not None:
        return existing
    app = QApplication(argv if argv is not None else sys.argv)
    icon_path = _resource_path("voice-studio.png")
    if icon_path.is_file():
        app.setWindowIcon(QIcon(str(icon_path)))
    return app


def build_app() -> MainWindow:
    return MainWindow()
