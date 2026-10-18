"""Single contextual STT progress surface in the Transcript inspector."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QProgressBar, QVBoxLayout, QWidget


def duration_label(seconds) -> str:
    if seconds is None:
        return "—"
    seconds = max(0, round(float(seconds)))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:d}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:02d}:{seconds:02d}"


class STTProgressStrip(QWidget):
    cancelRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sttProgressStrip")
        self._filename = ""
        self._prefix = ""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(5)
        heading = QHBoxLayout()
        self.heading = QLabel("Transcribing audio")
        heading.setObjectName("sttProgressHeading")
        heading.addWidget(self.heading, 1)
        self.percent = QLabel()
        self.percent.setAlignment(Qt.AlignmentFlag.AlignRight)
        heading.addWidget(self.percent)
        layout.addLayout(heading)
        self.source = QLabel()
        self.source.setWordWrap(False)
        layout.addWidget(self.source)
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(False)
        layout.addWidget(self.progress_bar)
        footer = QHBoxLayout()
        self.detail = QLabel()
        self.detail.setWordWrap(True)
        footer.addWidget(self.detail, 1)
        self.cancel_button = QPushButton("Cancel jobs")
        self.cancel_button.setToolTip("Cancel queued and running project jobs")
        self.cancel_button.clicked.connect(self.cancelRequested.emit)
        footer.addWidget(self.cancel_button)
        layout.addLayout(footer)
        self.hide()

    def clear(self):
        self.hide()
        self.source.clear()
        self.detail.clear()
        self.percent.clear()

    def _elide_source(self):
        label = self._prefix + self._filename
        available = max(80, self.width() - 22)
        self.source.setText(self.source.fontMetrics().elidedText(
            label, Qt.TextElideMode.ElideMiddle, available))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._filename:
            self._elide_source()

    def show_progress(self, info: dict) -> None:
        state = str(info.get("state", "queued"))
        filename = str(info.get("filename", ""))
        self._filename = filename
        device = str(info.get("device", "cpu")).upper()
        model = str(info.get("model", ""))
        index = int(info.get("source_index", 1))
        count = int(info.get("source_count", 1))
        prefix = f"Source {index}/{count} · " if count > 1 else ""
        self._prefix = prefix
        self._elide_source()
        self.source.setToolTip(filename)
        self.heading.setText({
            "completed": "Transcription complete",
            "failed": "Transcription failed",
            "cancelled": "Transcription cancelled",
            "queued": "Waiting to transcribe",
        }.get(state, "Transcribing audio"))
        processed, total = info.get("processed_seconds"), info.get("total_seconds")
        fraction = max(0., min(1., float(info.get("fraction") or 0.)))
        terminal = state in ("completed", "failed", "cancelled")
        self.cancel_button.setVisible(not terminal)
        self.progress_bar.setRange(0, 1000 if total and total > 0 or terminal else 0)
        if total and total > 0 or terminal:
            self.progress_bar.setValue(1000 if state == "completed" else round(fraction * 1000))
        self.percent.setText(f"{round((1. if state == 'completed' else fraction) * 100)}%" if total else "")
        eta = info.get("eta_seconds")
        elapsed = duration_label(info.get("elapsed_seconds"))
        if total and total > 0:
            amount = f"{duration_label(processed or 0)} / {duration_label(total)} audio"
            detail = amount + f" · Elapsed {elapsed}"
        else:
            detail = f"Elapsed {elapsed}"
        if state == "failed":
            detail += " · See job error"
        elif state == "cancelled":
            detail += " · Cancelled"
        elif state == "queued":
            detail += " · Waiting"
        elif not terminal:
            detail += " · " + (f"ETA {duration_label(eta)}" if eta is not None else "Estimating…")
        self.detail.setText(detail)
        self.detail.setToolTip(f"{model} · {device} · {info.get('stage', '')}")
        self.setToolTip(f"{model} · {device}")
        self.setVisible(True)
