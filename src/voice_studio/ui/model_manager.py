"""Settings → Models: background lifecycle operations and explicit recovery."""
from __future__ import annotations

from pathlib import Path
from threading import Event

from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QMessageBox,
    QProgressBar, QPushButton, QVBoxLayout,
)

from ..model_catalog import descriptors, get_model
from ..model_service import Cancelled, ModelService


class ModelWorker(QThread):
    progress = Signal(str, object, object, float)
    succeeded = Signal()
    failed = Signal(str)

    def __init__(self, service, model, operation, folder=None, parent=None):
        super().__init__(parent)
        self.service, self.model, self.operation, self.folder = service, model, operation, folder
        self.cancel = Event()

    def run(self):
        try:
            kwargs = {"cancel": self.cancel, "progress": self.progress.emit}
            if self.operation == "import":
                self.service.import_local(self.model, self.folder, **kwargs)
            elif self.operation == "remove":
                self.service.remove(self.model)
            else:
                getattr(self.service, self.operation)(self.model, **kwargs)
            self.succeeded.emit()
        except Exception as exc:
            self.failed.emit(str(exc))


class ModelManagerDialog(QDialog):
    modelsChanged = Signal()

    def __init__(self, parent=None, model_id=None, service=None):
        super().__init__(parent)
        self.service = service or ModelService()
        self._worker = None
        self.setWindowTitle("Settings → Models · Voice Studio")
        self.resize(740, 510)
        layout = QVBoxLayout(self)
        notice = QLabel("Downloads are explicit. Verify licenses before installing. Local hashes are not publisher signatures.")
        notice.setWordWrap(True)
        layout.addWidget(notice)
        storage = QHBoxLayout()
        self.storage = QLabel()
        self.storage.setWordWrap(True)
        self.storage_button = QPushButton("Change storage…")
        self.storage_button.clicked.connect(self._storage)
        storage.addWidget(self.storage, 1)
        storage.addWidget(self.storage_button)
        layout.addLayout(storage)
        self.category = QComboBox()
        for label, value in (("All models", None), ("STT", "stt"), ("Speaker matching", "locator"), ("Diarization", "diarization")):
            self.category.addItem(label, value)
        self.category.currentIndexChanged.connect(self._populate)
        layout.addWidget(self.category)
        self.model = QComboBox()
        self.model.currentIndexChanged.connect(self.refresh)
        layout.addWidget(self.model)
        self.details = QLabel()
        self.details.setWordWrap(True)
        self.details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.details, 1)
        self.actions = {}
        for row in (("Install / repair", "Import local folder…", "Discover legacy…"), ("Verify integrity", "Test readiness", "Use as default", "Remove / unlink")):
            buttons = QHBoxLayout()
            for text in row:
                button = QPushButton(text)
                self.actions[text] = button
                buttons.addWidget(button)
            layout.addLayout(buttons)
        self.install_button = self.actions["Install / repair"]
        self.remove_button = self.actions["Remove / unlink"]
        self.install_button.clicked.connect(lambda: self._start("install"))
        self.actions["Import local folder…"].clicked.connect(self._import)
        self.actions["Discover legacy…"].clicked.connect(self._discover)
        self.actions["Verify integrity"].clicked.connect(lambda: self._start("verify"))
        self.actions["Test readiness"].clicked.connect(lambda: self._start("ready"))
        self.actions["Use as default"].clicked.connect(self._default)
        self.remove_button.clicked.connect(self._remove)
        self.progress = QProgressBar()
        layout.addWidget(self.progress)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.cancel_button = QPushButton("Cancel operation")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._cancel)
        layout.addWidget(self.cancel_button)
        self._populate()
        if model_id:
            self.model.setCurrentIndex(max(0, self.model.findData(model_id)))

    def _populate(self):
        selected = self.model.currentData()
        self.model.blockSignals(True)
        self.model.clear()
        for entry in descriptors(self.category.currentData()):
            self.model.addItem(entry.label, entry.id)
        self.model.setCurrentIndex(max(0, self.model.findData(selected)))
        self.model.blockSignals(False)
        self.refresh()

    def refresh(self):
        if self.model.currentData() is None:
            return
        entry = get_model(self.model.currentData())
        status = self.service.status(entry)
        busy = self._worker is not None and self._worker.isRunning()
        locked = self.service.busy(entry)
        imported = entry.id in self.service.preferences().get("imports", {})
        self.storage.setText(f"Model storage: {self.service.root}\nProjects and settings are preserved when storage changes.")
        self.details.setText(
            f"{entry.label} · {entry.engine}\nSource: {entry.source}\nRevision: {entry.revision or 'publisher SHA-256'}\n"
            f"License/access: {entry.license}\n{entry.access}\nDevices: {', '.join(entry.devices)} · Languages: {', '.join(entry.languages)}\n"
            f"Size: {f'{entry.expected_size_bytes / 2**20:.1f} MiB' if entry.expected_size_bytes else 'reported by provider during download'}\n"
            f"Status: {status.state} · {'Verified locally' if status.verified else 'Not verified'}\nPath: {status.path}\n"
            f"{'External folder: unlinking never deletes its files. ' if imported else ''}{status.detail}"
        )
        for button in self.actions.values():
            button.setEnabled(not busy and not locked)
        self.install_button.setEnabled(not busy and not locked and entry.provider != "local-folder" and not imported)
        self.actions["Verify integrity"].setEnabled(not busy and not locked and self.service.manifest_path(entry).is_file())
        self.actions["Test readiness"].setEnabled(not busy and not locked and status.state in ("Installed", "Ready"))
        self.storage_button.setEnabled(not busy and not locked)
        self.model.setEnabled(not busy)
        self.category.setEnabled(not busy)
        self.cancel_button.setEnabled(busy)

    def _start(self, operation, folder=None):
        if self._worker and self._worker.isRunning():
            return
        model = get_model(self.model.currentData())
        self._worker = ModelWorker(self.service, model, operation, folder, self)
        self._worker.progress.connect(self._progress)
        self._worker.succeeded.connect(lambda: self.status.setText("Operation completed. Test readiness before queueing inference."))
        self._worker.failed.connect(self.status.setText)
        self._worker.finished.connect(self._finished)
        self.status.setText("Working…")
        self.progress.setRange(0, 0)
        self._worker.start()
        self.refresh()

    def _progress(self, stage, done, total, speed):
        self.progress.setRange(0, 1000 if total else 0)
        if total:
            self.progress.setValue(int(done / total * 1000))
        self.status.setText(f"{stage} · {done / 2**20:.1f}/{total / 2**20:.1f} MiB · {speed / 2**20:.1f} MiB/s")

    def _finished(self):
        self.progress.setRange(0, 1000)
        self.modelsChanged.emit()
        self.refresh()

    def _cancel(self):
        if self._worker:
            self._worker.cancel.set()
            self.status.setText("Cancelling; waiting for the current bounded network read…")

    def _import(self):
        folder = QFileDialog.getExistingDirectory(self, "Select complete local model folder (linked, never copied)")
        if folder:
            if QMessageBox.question(self, "Link external model", "Files stay in this folder and will not be copied. Moving the app alone will not move these weights. Continue?") == QMessageBox.StandardButton.Yes:
                self._start("import", Path(folder))

    def _discover(self):
        candidates = self.service.discover(get_model(self.model.currentData()))
        if not candidates:
            self.status.setText("No legacy model found. Use Import local folder to choose another location.")
            return
        from PySide6.QtWidgets import QInputDialog
        chosen, ok = QInputDialog.getItem(self, "Legacy models", "Link an existing folder without copying/deleting it:", [str(p) for p in candidates], editable=False)
        if ok:
            self._start("import", Path(chosen))

    def _default(self):
        self.service.set_default(get_model(self.model.currentData()))
        self.modelsChanged.emit()
        self.status.setText("Inference default saved beside the app.")

    def _storage(self):
        folder = QFileDialog.getExistingDirectory(self, "Choose model storage")
        if not folder:
            return
        if QMessageBox.question(self, "Change model storage", "Existing weights stay where they are. Use Import to link them. An external directory reduces portability. Continue?") != QMessageBox.StandardButton.Yes:
            return
        try:
            self.service.set_storage(Path(folder))
        except (OSError, ValueError) as exc:
            self.status.setText(str(exc))
        self.modelsChanged.emit()
        self.refresh()

    def _remove(self):
        if QMessageBox.question(self, "Remove model", "Delete managed weights/partial downloads, or unlink an external folder? External files and projects are preserved.") == QMessageBox.StandardButton.Yes:
            self._start("remove")

    def closeEvent(self, event):
        if self._worker and self._worker.isRunning():
            self._cancel()
            event.ignore()
        else:
            super().closeEvent(event)
