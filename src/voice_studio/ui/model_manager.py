"""Qt model manager: explicit install/remove, never download on startup."""
from __future__ import annotations

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QComboBox, QDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QVBoxLayout,
)

from ..model_registry import descriptors, get_model, installed, install, preflight, uninstall


class _InstallWorker(QThread):
    finished_install = Signal(str)
    failed_install = Signal(str)
    def __init__(self, model_id: str):
        super().__init__()
        self.model_id = model_id
    def run(self) -> None:
        try:
            install(get_model(self.model_id))
        except Exception as exc:
            self.failed_install.emit(str(exc))
        else:
            self.finished_install.emit(self.model_id)


class ModelManagerDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Model Manager · Voice Studio")
        self.resize(560, 230)
        self._worker: _InstallWorker | None = None
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Model assets are downloaded only when requested. Check licenses before installing."))
        self.model = QComboBox()
        for entry in descriptors():
            self.model.addItem(f"{entry.task.upper()} · {entry.label}", entry.id)
        self.model.currentIndexChanged.connect(self.refresh)
        layout.addWidget(self.model)
        self.details = QLabel()
        self.details.setWordWrap(True)
        layout.addWidget(self.details)
        actions = QHBoxLayout()
        self.install_button = QPushButton("Install / repair")
        self.remove_button = QPushButton("Remove")
        self.install_button.clicked.connect(self._install)
        self.remove_button.clicked.connect(self._remove)
        actions.addWidget(self.install_button)
        actions.addWidget(self.remove_button)
        layout.addLayout(actions)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.refresh()

    def refresh(self) -> None:
        entry = get_model(str(self.model.currentData()))
        ready = installed(entry)
        busy = self._worker is not None and self._worker.isRunning()
        self.install_button.setEnabled(not busy and entry.provider != "local-folder")
        self.details.setText(
            f"Engine: {entry.engine} · Source: {entry.source}\n"
            f"License: {entry.license}\n"
            f"Status: {'Installed · verified locally' if ready else 'Not installed / incomplete'}"
        )
        import sys
        self.remove_button.setEnabled(
            not busy and ready and not (getattr(sys, "frozen", False) and entry.task == "locator")
        )
        self.status.setText("CPU preflight: " + ("; ".join(preflight(entry)) or "Ready"))

    def _install(self) -> None:
        if self._worker and self._worker.isRunning():
            return
        entry = get_model(str(self.model.currentData()))
        if installed(entry):
            return
        self._worker = _InstallWorker(entry.id)
        self._worker.finished_install.connect(self._done)
        self._worker.failed_install.connect(self._failed)
        self.install_button.setEnabled(False)
        self.remove_button.setEnabled(False)
        self.status.setText("Installing model in background…")
        self._worker.start()

    def _done(self, _model_id: str) -> None:
        self.install_button.setEnabled(True)
        self.refresh()

    def _failed(self, message: str) -> None:
        self.install_button.setEnabled(True)
        self.refresh()
        QMessageBox.warning(self, "Model installation failed", message)

    def _remove(self) -> None:
        if self._worker and self._worker.isRunning():
            return
        entry = get_model(str(self.model.currentData()))
        confirmation = QMessageBox.question(
            self, "Remove model", f"Delete local files for {entry.label}?"
        )
        if confirmation != QMessageBox.StandardButton.Yes:
            return
        uninstall(entry)
        self.refresh()

    def closeEvent(self, event):
        if self._worker and self._worker.isRunning():
            self.status.setText("Installation in progress; this window cannot close yet.")
            event.ignore()
        else:
            super().closeEvent(event)
