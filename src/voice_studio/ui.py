from __future__ import annotations

import sys
import tempfile
import uuid
from pathlib import Path

from PySide6.QtCore import QPoint, Qt, QThread, QUrl, Signal, Slot
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPolygon
from PySide6.QtMultimedia import (
    QAudioInput,
    QAudioOutput,
    QMediaCaptureSession,
    QMediaFormat,
    QMediaPlayer,
    QMediaRecorder,
)
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSlider,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from .config import DEFAULT_THRESHOLD
from .pipeline import AnalysisBundle
from .profiles import DEFAULT_PROFILE_KEY, INFERENCE_PROFILES, get_inference_profile
from .service import analyze_bundle


SCENARIOS = [
    "Họp / hội thảo",
    "Phỏng vấn / thảo luận",
    "Podcast / bản ghi âm",
    "Khác",
]

PROFILE_CHOICES = [(profile.label, profile.key) for profile in INFERENCE_PROFILES.values()]
DEFAULT_REFERENCE_SPEAKERS = 1
MAX_REFERENCE_SPEAKERS = 3
SEGMENT_HEADERS = ["Người nói", "Bắt đầu", "Kết thúc", "Peak"]

TRACK_COLORS = [
    QColor("#36c5d8"),
    QColor("#a78bfa"),
    QColor("#f6b94a"),
]

APP_STYLESHEET = """
QMainWindow, QWidget {
    background: #15171b;
    color: #e7e9ee;
    font-size: 13px;
}
QFrame#toolbar, QFrame#panel {
    background: #1c1f24;
    border: 1px solid #2b3037;
    border-radius: 8px;
}
QGroupBox {
    border: 1px solid #31363f;
    border-radius: 7px;
    margin-top: 10px;
    padding-top: 8px;
    font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
}
QPushButton {
    background: #252a31;
    border: 1px solid #383f49;
    border-radius: 6px;
    padding: 7px 11px;
}
QPushButton:hover {
    background: #2d333c;
}
QPushButton:disabled {
    color: #777d86;
}
QPushButton#primaryButton {
    background: #18a9bb;
    border-color: #18a9bb;
    color: #081114;
    font-weight: 700;
}
QPushButton#primaryButton:hover {
    background: #31bdce;
}
QLineEdit, QComboBox, QDoubleSpinBox {
    background: #111318;
    border: 1px solid #363c45;
    border-radius: 5px;
    padding: 6px;
}
QTabWidget::pane {
    border: 1px solid #2b3037;
    background: #181b20;
}
QTabBar::tab {
    background: #1c1f24;
    color: #aeb4bd;
    padding: 8px 13px;
    border: 1px solid #2b3037;
}
QTabBar::tab:selected {
    color: #ffffff;
    background: #252a31;
}
QTableWidget {
    background: #111318;
    alternate-background-color: #171a1f;
    gridline-color: #2c3138;
    border: 1px solid #2c3138;
}
QHeaderView::section {
    background: #22262c;
    color: #d9dde3;
    border: 0;
    border-right: 1px solid #333942;
    padding: 6px;
}
QSlider::groove:horizontal {
    height: 4px;
    background: #30353d;
}
QSlider::handle:horizontal {
    background: #e8ebef;
    width: 12px;
    margin: -5px 0;
    border-radius: 6px;
}
"""


def _fmt_time(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    minutes = int(seconds // 60)
    remain = seconds - minutes * 60
    if minutes:
        return f"{minutes:02d}:{remain:04.1f}"
    return f"{remain:.1f}s"


def _parse_timecode(value: object) -> float:
    text = str(value or "").strip()
    if not text:
        raise ValueError("Timestamp trống.")
    if text.endswith("s"):
        return float(text[:-1])
    if ":" in text:
        minutes, seconds = text.split(":", 1)
        return int(minutes) * 60.0 + float(seconds)
    return float(text)


def _resource_path(filename: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return base / "assets" / filename


class AnalysisWorker(QThread):
    completed = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        references,
        target_audio,
        target_video,
        threshold: float,
        scenario: str,
        profile_key: str,
    ):
        super().__init__()
        self._references = references
        self._target_audio = target_audio
        self._target_video = target_video
        self._threshold = threshold
        self._scenario = scenario
        self._profile_key = profile_key

    def run(self) -> None:
        try:
            bundle, resolved_threshold = analyze_bundle(
                self._references,
                self._target_audio,
                self._target_video,
                self._threshold,
                profile_key=self._profile_key,
            )
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.completed.emit(
            (bundle, resolved_threshold, self._scenario, self._profile_key)
        )


class DetectionOverlay(QWidget):
    """Paint current speaker matches directly over the media preview."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._bundle: AnalysisBundle | None = None
        self._position_seconds = 0.0
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

    def set_bundle(self, bundle: AnalysisBundle | None) -> None:
        self._bundle = bundle
        self.update()

    def set_position(self, seconds: float) -> None:
        self._position_seconds = max(0.0, seconds)
        self.update()

    def _active_results(self):
        if self._bundle is None:
            return []
        active = []
        for result in self._bundle.results:
            segment = next(
                (
                    segment
                    for segment in result.segments
                    if segment.start <= self._position_seconds <= segment.end
                ),
                None,
            )
            if segment is not None:
                active.append((result, segment))
        return active

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().paintEvent(event)
        active = self._active_results()
        if not active:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        margin = 18
        chip_height = 36
        gap = 8
        y = self.height() - margin - chip_height

        for index, (result, segment) in enumerate(reversed(active)):
            label = f"{result.name}  ·  {segment.max_score:.2f}"
            metrics = painter.fontMetrics()
            width = min(self.width() - 2 * margin, metrics.horizontalAdvance(label) + 34)
            x = margin
            color = TRACK_COLORS[(len(active) - index - 1) % len(TRACK_COLORS)]
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(10, 12, 16, 218))
            painter.drawRoundedRect(x, y, width, chip_height, 8, 8)
            painter.setBrush(color)
            painter.drawRoundedRect(x + 7, y + 7, 5, chip_height - 14, 2, 2)
            painter.setPen(QColor("#f5f7fa"))
            painter.drawText(
                x + 20,
                y,
                width - 26,
                chip_height,
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                label,
            )
            y -= chip_height + gap


class PreviewVideoWidget(QVideoWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.overlay = DetectionOverlay(self)
        self.overlay.setGeometry(self.rect())
        self.overlay.raise_()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        self.overlay.setGeometry(self.rect())
        self.overlay.raise_()


class EditorTimelineWidget(QWidget):
    """Video-editor style speaker tracks with ruler, clips and a synced playhead."""

    seekRequested = Signal(float)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._bundle: AnalysisBundle | None = None
        self._duration = 0.0
        self._position_seconds = 0.0
        self.setMinimumHeight(205)

    def set_bundle(self, bundle: AnalysisBundle | None) -> None:
        self._bundle = bundle
        if bundle is not None:
            self._duration = max(self._duration, bundle.duration)
        self.update()

    def set_duration_seconds(self, duration: float) -> None:
        self._duration = max(0.0, float(duration))
        self.update()

    def set_position_seconds(self, seconds: float) -> None:
        self._position_seconds = max(0.0, float(seconds))
        self.update()

    def _track_rect(self):
        return self.rect().adjusted(112, 30, -16, -16)

    def _duration_seconds(self) -> float:
        if self._bundle is not None:
            return max(self._bundle.duration, self._duration, 0.001)
        return max(self._duration, 0.001)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#111318"))

        rect = self._track_rect()
        duration = self._duration_seconds()

        painter.setPen(QColor("#828995"))
        ticks = 6
        for index in range(ticks + 1):
            ratio = index / ticks
            x = rect.left() + int(rect.width() * ratio)
            painter.drawLine(x, 18, x, 28)
            label = _fmt_time(duration * ratio)
            painter.drawText(x - 22, 14, 58, 14, Qt.AlignmentFlag.AlignLeft, label)

        results = self._bundle.results if self._bundle is not None else []
        lane_count = max(1, len(results))
        lane_height = max(32, rect.height() // lane_count)

        for lane_index in range(lane_count):
            top = rect.top() + lane_index * lane_height
            lane_rect = rect.adjusted(0, lane_index * lane_height, 0, 0)
            lane_rect.setHeight(lane_height - 3)
            painter.fillRect(
                lane_rect,
                QColor("#171a1f") if lane_index % 2 == 0 else QColor("#14171b"),
            )
            painter.setPen(QColor("#2d323a"))
            painter.drawLine(rect.left(), top + lane_height - 2, rect.right(), top + lane_height - 2)

            if lane_index >= len(results):
                continue

            result = results[lane_index]
            color = TRACK_COLORS[lane_index % len(TRACK_COLORS)]
            painter.setPen(QColor("#cfd4db"))
            painter.drawText(
                8,
                top,
                96,
                lane_height - 3,
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                result.name,
            )

            for segment in result.segments:
                x1 = rect.left() + int(rect.width() * segment.start / duration)
                x2 = rect.left() + int(rect.width() * segment.end / duration)
                clip = lane_rect.adjusted(x1 - rect.left() + 2, 5, x2 - rect.right() - 2, -5)
                if clip.width() < 5:
                    clip.setWidth(5)

                active = segment.start <= self._position_seconds <= segment.end
                fill = QColor(color)
                fill.setAlpha(225 if active else 150)
                painter.setPen(color.lighter(125) if active else color)
                painter.setBrush(fill)
                painter.drawRoundedRect(clip, 5, 5)

                if clip.width() > 72:
                    painter.setPen(QColor("#0a0d10"))
                    painter.drawText(
                        clip.adjusted(7, 0, -4, 0),
                        Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                        f"{segment.max_score:.2f}",
                    )

        playhead_ratio = min(1.0, max(0.0, self._position_seconds / duration))
        playhead_x = rect.left() + int(rect.width() * playhead_ratio)
        playhead_pen = QPen(QColor("#ff5d73"))
        playhead_pen.setWidth(2)
        painter.setPen(playhead_pen)
        painter.drawLine(playhead_x, 12, playhead_x, rect.bottom())
        painter.setBrush(QColor("#ff5d73"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPolygon(
            QPolygon(
                [
                    QPoint(playhead_x - 6, 8),
                    QPoint(playhead_x + 6, 8),
                    QPoint(playhead_x, 16),
                ]
            )
        )

        if self._bundle is None:
            painter.setPen(QColor("#777f8b"))
            painter.drawText(
                rect,
                Qt.AlignmentFlag.AlignCenter,
                "Analyze để tạo speaker tracks trên timeline",
            )

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt API
        rect = self._track_rect()
        if rect.width() <= 0 or event.position().x() < rect.left():
            return
        ratio = (event.position().x() - rect.left()) / rect.width()
        seconds = max(0.0, min(self._duration_seconds(), ratio * self._duration_seconds()))
        self.seekRequested.emit(seconds)
        super().mousePressEvent(event)


class SimilarityPlotWidget(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._bundle: AnalysisBundle | None = None
        self._threshold = DEFAULT_THRESHOLD
        self.setMinimumHeight(160)

    def set_bundle(self, bundle: AnalysisBundle | None, threshold: float) -> None:
        self._bundle = bundle
        self._threshold = threshold
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#111318"))
        rect = self.rect().adjusted(38, 14, -12, -24)

        if self._bundle is None or not self._bundle.results:
            painter.setPen(QColor("#777f8b"))
            painter.drawText(
                self.rect(), Qt.AlignmentFlag.AlignCenter, "Similarity diagnostics"
            )
            return

        duration = max(self._bundle.duration, 0.001)
        painter.setPen(QPen(QColor("#353b44")))
        painter.drawRect(rect)

        threshold_y = rect.bottom() - int(rect.height() * self._threshold)
        threshold_pen = QPen(QColor("#8d96a3"))
        threshold_pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(threshold_pen)
        painter.drawLine(rect.left(), threshold_y, rect.right(), threshold_y)

        for index, result in enumerate(self._bundle.results):
            if not result.scores:
                continue
            pen = QPen(TRACK_COLORS[index % len(TRACK_COLORS)])
            pen.setWidth(2)
            painter.setPen(pen)
            previous = None
            for score in result.scores:
                center = (score.start + score.end) / 2.0
                x = rect.left() + int(rect.width() * center / duration)
                normalized = max(0.0, min(1.0, float(score.score)))
                y = rect.bottom() - int(rect.height() * normalized)
                if previous is not None:
                    painter.drawLine(previous[0], previous[1], x, y)
                previous = (x, y)


class ReferenceInput(QGroupBox):
    def __init__(self, index: int, parent: QWidget | None = None):
        super().__init__(f"Speaker {index}", parent)
        self.audio_path: str | None = None
        self._record_path: str | None = None
        self._audio_input: QAudioInput | None = None
        self._recorder: QMediaRecorder | None = None
        self._capture_session: QMediaCaptureSession | None = None
        self.setMaximumHeight(118)

        layout = QGridLayout(self)
        layout.setContentsMargins(8, 8, 8, 7)
        layout.setHorizontalSpacing(6)
        layout.setVerticalSpacing(5)

        self.name_edit = QLineEdit()
        self.name_edit.setText(f"Speaker {index}")
        self.path_label = QLabel("Chưa có audio")
        self.path_label.setStyleSheet("color: #9aa1ab;")
        choose_button = QPushButton("📁 File")
        self.record_button = QPushButton("● Record")
        clear_button = QPushButton("Clear")

        choose_button.clicked.connect(self._choose_audio)
        self.record_button.clicked.connect(self._toggle_recording)
        clear_button.clicked.connect(self.clear)

        layout.addWidget(self.name_edit, 0, 0, 1, 3)
        layout.addWidget(self.path_label, 1, 0, 1, 3)
        layout.addWidget(choose_button, 2, 0)
        layout.addWidget(self.record_button, 2, 1)
        layout.addWidget(clear_button, 2, 2)

    def value(self) -> tuple[str, str | None]:
        return self.name_edit.text().strip(), self.audio_path

    @Slot()
    def clear(self) -> None:
        if (
            self._recorder
            and self._recorder.recorderState()
            == QMediaRecorder.RecorderState.RecordingState
        ):
            self._recorder.stop()
        self.audio_path = None
        self.path_label.setText("Chưa có audio")
        self.record_button.setText("● Record")

    @Slot()
    def _choose_audio(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Chọn reference audio",
            "",
            "Audio (*.wav *.flac *.ogg *.mp3 *.m4a);;Tất cả file (*)",
        )
        if path:
            self.audio_path = path
            self.path_label.setText(Path(path).name)

    @Slot()
    def _toggle_recording(self) -> None:
        if (
            self._recorder
            and self._recorder.recorderState()
            == QMediaRecorder.RecorderState.RecordingState
        ):
            self._recorder.stop()
            self.record_button.setText("● Record")
            if self._record_path:
                self.audio_path = self._record_path
                self.path_label.setText(Path(self._record_path).name)
            return

        record_path = str(
            Path(tempfile.gettempdir())
            / f"voice-studio-ref-{uuid.uuid4().hex}.wav"
        )
        audio_input = QAudioInput(self)
        recorder = QMediaRecorder(self)
        capture_session = QMediaCaptureSession(self)
        capture_session.setAudioInput(audio_input)
        capture_session.setRecorder(recorder)

        media_format = QMediaFormat()
        media_format.setFileFormat(QMediaFormat.FileFormat.Wave)
        recorder.setMediaFormat(media_format)
        recorder.setOutputLocation(QUrl.fromLocalFile(record_path))
        recorder.errorOccurred.connect(
            lambda _error, message: self._recording_error(message)
        )

        self._audio_input = audio_input
        self._recorder = recorder
        self._capture_session = capture_session
        self._record_path = record_path
        recorder.record()
        self.record_button.setText("■ Stop")
        self.path_label.setText("Đang ghi âm…")

    def _recording_error(self, message: str) -> None:
        self.record_button.setText("● Record")
        QMessageBox.warning(
            self,
            "Không thể ghi âm",
            message or "Qt Multimedia không thể mở microphone.",
        )


class MainWindow(QMainWindow):
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

        tabs = QTabWidget()
        self.analysis_page = self._build_analysis_tab()
        tabs.addTab(self.analysis_page, "🎬 Workspace")
        tabs.addTab(self._build_help_tab(), "ℹ️ Help")
        tabs.addTab(self._build_privacy_tab(), "🛡️ Quyền riêng tư")
        self.setCentralWidget(tabs)

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

        self.analyze_button = QPushButton("Analyze")
        self.analyze_button.setObjectName("primaryButton")
        self.analyze_button.clicked.connect(self._start_analysis)

        toolbar_layout.addWidget(title)
        toolbar_layout.addSpacing(14)
        toolbar_layout.addWidget(self.target_mode)
        toolbar_layout.addWidget(choose_target)
        toolbar_layout.addWidget(self.target_label, 1)
        toolbar_layout.addWidget(self.analyze_button)
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
        self.inspector_tabs.addTab(self._build_speakers_panel(), "Speakers")
        self.inspector_tabs.addTab(self._build_analysis_panel(), "Analysis")
        self.inspector_tabs.addTab(self._build_segments_panel(), "Segments")

        self.workspace_splitter.addWidget(preview_panel)
        self.workspace_splitter.addWidget(self.inspector_tabs)
        self.workspace_splitter.setStretchFactor(0, 1)
        self.workspace_splitter.setStretchFactor(1, 0)
        self.workspace_splitter.setSizes([960, 390])

        timeline_panel = QFrame()
        timeline_panel.setObjectName("panel")
        timeline_layout = QVBoxLayout(timeline_panel)
        timeline_layout.setContentsMargins(8, 7, 8, 8)
        timeline_layout.setSpacing(4)

        timeline_header = QHBoxLayout()
        timeline_header.addWidget(QLabel("<b>Speaker timeline</b>"))
        self.summary_label = QLabel("Open a target, add reference voices, then Analyze.")
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

    def _build_speakers_panel(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 8, 8, 8)
        info = QLabel(f"Reference audio · 3–5 giây rõ tiếng · tối đa {MAX_REFERENCE_SPEAKERS} speakers")
        info.setStyleSheet("color: #9da4ae;")
        layout.addWidget(info)

        self.reference_inputs: list[ReferenceInput] = []
        self.reference_list_layout = QVBoxLayout()
        self.reference_list_layout.setContentsMargins(0, 0, 0, 0)
        self.reference_list_layout.setSpacing(6)
        layout.addLayout(self.reference_list_layout)

        self.add_speaker_button = QPushButton("+ Add speaker")
        self.add_speaker_button.clicked.connect(self._add_reference_input)
        layout.addWidget(self.add_speaker_button)
        layout.addStretch(1)

        for _ in range(DEFAULT_REFERENCE_SPEAKERS):
            self._add_reference_input()
        return page

    @Slot()
    def _add_reference_input(self) -> None:
        if len(self.reference_inputs) >= MAX_REFERENCE_SPEAKERS:
            return

        index = len(self.reference_inputs) + 1
        reference = ReferenceInput(index)
        self.reference_inputs.append(reference)
        self.reference_list_layout.addWidget(reference)

        reached_limit = len(self.reference_inputs) >= MAX_REFERENCE_SPEAKERS
        self.add_speaker_button.setEnabled(not reached_limit)
        self.add_speaker_button.setText(
            f"Maximum {MAX_REFERENCE_SPEAKERS} speakers"
            if reached_limit
            else "+ Add speaker"
        )

    def _build_analysis_panel(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 8, 8, 8)

        settings_group = QGroupBox("Inference")
        form = QFormLayout(settings_group)
        self.scenario = QComboBox()
        self.scenario.addItems(SCENARIOS)

        self.profile = QComboBox()
        for label, key in PROFILE_CHOICES:
            self.profile.addItem(label, key)
        self.profile.setCurrentIndex(max(0, self.profile.findData(DEFAULT_PROFILE_KEY)))
        self.profile.currentIndexChanged.connect(self._apply_profile_default)

        self.threshold = QDoubleSpinBox()
        self.threshold.setRange(0.20, 0.90)
        self.threshold.setDecimals(2)
        self.threshold.setSingleStep(0.01)
        self.threshold.setValue(DEFAULT_THRESHOLD)

        self.profile_help = QLabel(get_inference_profile(DEFAULT_PROFILE_KEY).description)
        self.profile_help.setWordWrap(True)
        self.profile_help.setStyleSheet("color: #9aa1ab;")

        form.addRow("Context", self.scenario)
        form.addRow("Accuracy", self.profile)
        form.addRow("Threshold", self.threshold)
        form.addRow("", self.profile_help)
        layout.addWidget(settings_group)

        plot_group = QGroupBox("Similarity")
        plot_layout = QVBoxLayout(plot_group)
        self.similarity_plot = SimilarityPlotWidget()
        plot_layout.addWidget(self.similarity_plot)
        layout.addWidget(plot_group, 1)
        return page

    def _build_segments_panel(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 8, 8, 8)

        self.segment_table = QTableWidget(0, len(SEGMENT_HEADERS))
        self.segment_table.setHorizontalHeaderLabels(SEGMENT_HEADERS)
        self.segment_table.setAlternatingRowColors(True)
        self.segment_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.segment_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.segment_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        for column in range(1, len(SEGMENT_HEADERS)):
            self.segment_table.horizontalHeader().setSectionResizeMode(
                column, QHeaderView.ResizeMode.ResizeToContents
            )
        self.segment_table.cellClicked.connect(self._seek_segment)
        layout.addWidget(self.segment_table)
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
            <p>Dữ liệu xử lý cục bộ. STT, diarization và batch project
            chưa được triển khai trong phiên bản này.</p>
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

    @Slot()
    def _apply_profile_default(self) -> None:
        profile = get_inference_profile(str(self.profile.currentData()))
        self.threshold.setValue(profile.default_threshold)
        self.profile_help.setText(profile.description)

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

        references = [reference.value() for reference in self.reference_inputs]
        is_video = self.target_mode.currentData() == "video"
        target_audio = None if is_video else self._target_path
        target_video = self._target_path if is_video else None
        threshold = self.threshold.value()
        profile_key = str(self.profile.currentData())

        self.analyze_button.setEnabled(False)
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
        )
        self._worker.completed.connect(self._analysis_complete)
        self._worker.failed.connect(self._analysis_failed)
        self._worker.finished.connect(self._analysis_finished)
        self._worker.start()

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
        seconds = max(0.0, position_ms / 1000.0)
        self.position_slider.blockSignals(True)
        self.position_slider.setValue(position_ms)
        self.position_slider.blockSignals(False)
        duration = max(0.0, self._player.duration() / 1000.0)
        self.time_label.setText(f"{_fmt_time(seconds)} / {_fmt_time(duration)}")
        self.timeline.set_position_seconds(seconds)
        self.video_widget.overlay.set_position(seconds)

    @Slot(int)
    def _on_player_duration(self, duration_ms: int) -> None:
        self.position_slider.setRange(0, max(0, duration_ms))
        self.timeline.set_duration_seconds(duration_ms / 1000.0)

    @Slot(object)
    def _on_playback_state(self, state: object) -> None:
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        self.play_button.setText("⏸" if playing else "▶")

    @Slot(float)
    def _seek_to_seconds(self, seconds: float) -> None:
        self._player.setPosition(int(max(0.0, seconds) * 1000))
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


def create_application(argv: list[str] | None = None) -> QApplication:
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
