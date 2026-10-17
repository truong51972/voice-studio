"""Optional source-cited local summary; AI prose cannot alter verified transcript."""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTextEdit, QVBoxLayout, QWidget,
)

from ...summarization import summary_markdown
from ...task_runtime import TaskManager, TaskRequest


class SummaryPanel(QWidget):
    startRequested = Signal()
    def __init__(self, stt_panel, parent=None, *, session=None):
        super().__init__(parent)
        self.stt_panel = stt_panel
        self.session = session
        self._manager = TaskManager(cpu_concurrency=1) if session is None else None
        self._job_id: str | None = None
        self._input_file: Path | None = None
        self.result: dict | None = None
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Optional Ollama on localhost · AI draft, not verbatim"))
        self.model = QLineEdit()
        self.model.setPlaceholderText("Installed Ollama model name (e.g. gemma3:4b)")
        layout.addWidget(self.model)
        buttons = QHBoxLayout()
        self.run_button = QPushButton("Generate local draft")
        self.run_button.clicked.connect(self.start)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel)
        self.export_button = QPushButton("Export MD + JSON")
        self.export_button.clicked.connect(self.export)
        buttons.addWidget(self.run_button)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.export_button)
        layout.addLayout(buttons)
        self.status = QLabel("Requires a reviewed transcript. No cloud API is used.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.preview = QTextEdit()
        self.preview.setReadOnly(True)
        layout.addWidget(self.preview, 1)
        self._timer = QTimer(self)
        self._timer.setInterval(150)
        self._timer.timeout.connect(self._poll)

    def reset(self) -> None:
        if self.session is None:
            self.cancel()
        self.result = None
        self.preview.clear()

    def start(self) -> None:
        if self.session is not None:
            self.startRequested.emit()
            return
        if self._job_id is not None:
            return
        document = self.stt_panel.document
        if document is None:
            self.status.setText("Transcribe/review the selected media first.")
            return
        model = self.model.text().strip()
        if not model:
            self.status.setText("Enter an already installed local Ollama model.")
            return
        import uuid
        self._input_file = self._manager.root / f"summary-input-{uuid.uuid4().hex}.json"
        self._input_file.write_text(
            json.dumps(document.serialize(), ensure_ascii=False), encoding="utf-8",
        )
        self._job_id = self._manager.submit(TaskRequest(kind="summary", inputs={
            "document_path": str(self._input_file),
            "model": model,
        }))
        self._manager.poll()
        self.run_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.status.setText("Running local Ollama. AI interpretation requires review.")
        self._timer.start()

    def _poll(self) -> None:
        if not self._job_id:
            return
        self._manager.poll()
        state = self._manager.snapshot(self._job_id)
        if state.state == "completed":
            try:
                self._show(self._manager.result(self._job_id))
            except Exception as exc:
                self.status.setText(f"Cannot render generated report: {exc}")
            self._finish()
        elif state.state == "failed":
            self.status.setText(state.error or "Local summary generation failed")
            self._finish()

    def _show(self, result: dict) -> None:
        self.result = result
        self.preview.setPlainText(summary_markdown(result))
        self.status.setText(
            f"{len(result['items'])} source-cited AI draft items. Review before use."
        )

    def export(self) -> None:
        if self.result is None:
            self.status.setText("Generate a report before exporting.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export local AI draft", "", "Markdown (*.md)",
        )
        if not path:
            return
        destination = Path(path)
        if destination.suffix.lower() != ".md":
            destination = destination.with_suffix(".md")
        destination.write_text(summary_markdown(self.result), encoding="utf-8")
        destination.with_suffix(".summary.json").write_text(
            json.dumps(self.result, ensure_ascii=False, indent=2), encoding="utf-8",
        )
        self.status.setText(f"Draft and provenance saved to {destination.name}")

    def cancel(self) -> None:
        if self.session is not None:
            self.session.cancel()
            return
        if self._job_id:
            self._manager.cancel(self._job_id)
            self._finish()
            self.status.setText("Local summary job cancelled.")

    def _finish(self) -> None:
        self._timer.stop()
        if self._job_id:
            self._manager.acknowledge(self._job_id)
        self._job_id = None
        if self._input_file is not None:
            self._input_file.unlink(missing_ok=True)
            self._input_file = None
        self.run_button.setEnabled(True)
        self.cancel_button.setEnabled(False)

    def closeEvent(self, event) -> None:
        if self.session is None:
            self.cancel()
        if self._manager is not None:
            self._manager.close()
        super().closeEvent(event)
