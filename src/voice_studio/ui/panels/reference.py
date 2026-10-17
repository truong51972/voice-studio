from __future__ import annotations

"""Known speaker enrollment by file or local microphone."""

import tempfile
import uuid
from pathlib import Path

from PySide6.QtCore import QUrl, Slot
from PySide6.QtMultimedia import QAudioInput, QMediaCaptureSession, QMediaFormat, QMediaRecorder
from PySide6.QtWidgets import (QFileDialog, QGridLayout, QGroupBox, QLabel,
                               QLineEdit, QMessageBox, QPushButton, QWidget)

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
