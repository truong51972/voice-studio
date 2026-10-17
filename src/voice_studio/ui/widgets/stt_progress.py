"""Compact, nonblocking STT job progress in the editor preview header."""
from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QVBoxLayout, QWidget


def duration_label(seconds) -> str:
    if seconds is None:
        return "—"
    seconds = max(0, round(float(seconds)))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:d}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:02d}:{seconds:02d}"


class STTProgressStrip(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sttProgressStrip")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(3)
        self.source = QLabel()
        self.source.setWordWrap(True)
        layout.addWidget(self.source)
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(True)
        layout.addWidget(self.progress_bar)
        self.detail = QLabel()
        self.detail.setWordWrap(True)
        layout.addWidget(self.detail)
        self.hide()

    def clear(self):
        self.hide()
        self.source.clear()
        self.detail.clear()

    def show_progress(self, info: dict) -> None:
        state = str(info.get("state", "queued"))
        stage = str(info.get("stage", "Queued"))
        filename = str(info.get("filename", ""))
        device = str(info.get("device", "cpu")).upper()
        model = str(info.get("model", ""))
        index = int(info.get("source_index", 1))
        count = int(info.get("source_count", 1))
        prefix = f"Source {index}/{count} · " if count > 1 else ""
        self.source.setText(f"{prefix}{filename} · {model} · {device} · {stage}")
        processed, total = info.get("processed_seconds"), info.get("total_seconds")
        fraction = max(0., min(1., float(info.get("fraction") or 0.)))
        elapsed = duration_label(info.get("elapsed_seconds"))
        terminal = state in ("completed", "failed", "cancelled")
        if state == "completed":
            self.progress_bar.setRange(0, 1000)
            self.progress_bar.setValue(1000)
            self.detail.setText(f"Completed · {duration_label(total)} audio · {elapsed} elapsed")
        elif total is not None and total > 0:
            self.progress_bar.setRange(0, 1000)
            self.progress_bar.setValue(round(fraction * 1000))
            amount = f"{duration_label(processed or 0)} / {duration_label(total)} ({fraction:.0%})"
            eta = info.get("eta_seconds")
            estimate = (f"ETA {duration_label(eta)}" if eta is not None else "Estimating…")
            final = state.capitalize() if terminal else estimate
            self.detail.setText(f"{amount} · Elapsed {elapsed} · {final}")
        else:
            self.progress_bar.setRange(0, 0) if not terminal else self.progress_bar.setRange(0, 1000)
            self.detail.setText(f"Audio duration unavailable · Elapsed {elapsed} · "
                                + (state.capitalize() if terminal else "Estimating…"))
        self.setVisible(True)
