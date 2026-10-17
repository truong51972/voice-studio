"""Settings → Models: scannable catalog with device-specific native readiness."""
from __future__ import annotations

from pathlib import Path
from threading import Event

from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
    QMenu, QMessageBox, QProgressBar, QPushButton, QSplitter,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from ..model_catalog import descriptors, get_model
from ..model_service import ModelService


class ModelWorker(QThread):
    progress = Signal(str, object, object, float)
    succeeded = Signal()
    failed = Signal(str)

    def __init__(self, service, model, operation, folder=None,
                 device="cpu", compute_type=None, parent=None):
        super().__init__(parent)
        self.service, self.model, self.operation = service, model, operation
        self.folder, self.device, self.compute_type = folder, device, compute_type
        self.cancel = Event()

    def run(self):
        try:
            kwargs = {"cancel": self.cancel, "progress": self.progress.emit}
            if self.operation == "import":
                self.service.import_local(self.model, self.folder, **kwargs)
            elif self.operation == "remove":
                self.service.remove(self.model)
            elif self.operation == "ready":
                self.service.ready(self.model, device=self.device,
                                   compute_type=self.compute_type, **kwargs)
            else:
                getattr(self.service, self.operation)(self.model, **kwargs)
            self.succeeded.emit()
        except Exception as exc:
            self.failed.emit(str(exc))


class ModelManagerDialog(QDialog):
    modelsChanged = Signal()

    _groups = (
        ("Speech to text", "stt"),
        ("Speaker matching", "locator"),
        ("Diarization", "diarization"),
    )

    def __init__(self, parent=None, model_id=None, service=None):
        super().__init__(parent)
        self.service = service or ModelService()
        self._worker = None
        self._selected_id = model_id
        self._items = {}
        self.setWindowTitle("Settings → Models · Voice Studio")
        self.resize(1020, 640)
        root = QVBoxLayout(self)

        headline = QHBoxLayout()
        headline.addWidget(QLabel("Models"), 1)
        self.storage_button = QPushButton("Change storage…")
        self.storage_button.clicked.connect(self._storage)
        headline.addWidget(self.storage_button)
        root.addLayout(headline)

        self.storage = QLabel()
        self.storage.setWordWrap(True)
        root.addWidget(self.storage)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        browser = QWidget()
        left = QVBoxLayout(browser)
        left.setContentsMargins(0, 0, 6, 0)
        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Find model…")
        self.search.textChanged.connect(self._populate)
        filters.addWidget(self.search, 1)
        self.category = QComboBox()
        for label, value in (("All", None), ("STT", "stt"), ("Matching", "locator"),
                             ("Diarization", "diarization")):
            self.category.addItem(label, value)
        self.category.currentIndexChanged.connect(self._populate)
        filters.addWidget(self.category)
        left.addLayout(filters)
        self.model_list = QTreeWidget()
        self.model_list.setColumnCount(2)
        self.model_list.setHeaderLabels(["Model", "Availability"])
        self.model_list.setRootIsDecorated(True)
        self.model_list.setAlternatingRowColors(True)
        self.model_list.setColumnWidth(0, 198)
        self.model_list.currentItemChanged.connect(self._selection)
        left.addWidget(self.model_list, 1)
        splitter.addWidget(browser)

        details_panel = QWidget()
        right = QVBoxLayout(details_panel)
        right.setContentsMargins(10, 0, 0, 0)
        self.model_title = QLabel()
        self.model_title.setStyleSheet("font-size: 19px; font-weight: 600;")
        right.addWidget(self.model_title)
        self.state_label = QLabel()
        self.state_label.setWordWrap(True)
        right.addWidget(self.state_label)
        self.runtime_label = QLabel()
        self.runtime_label.setWordWrap(True)
        right.addWidget(self.runtime_label)
        self.details = QLabel()
        self.details.setWordWrap(True)
        self.details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.details.setAlignment(Qt.AlignmentFlag.AlignTop)
        right.addWidget(self.details, 1)

        precision = QHBoxLayout()
        precision.addWidget(QLabel("GPU precision"))
        self.precision = QComboBox()
        self.precision.addItem("FP16 · fast", "float16")
        self.precision.addItem("INT8 + FP16 · lower VRAM", "int8_float16")
        self.precision.currentIndexChanged.connect(self.refresh)
        precision.addWidget(self.precision, 1)
        right.addLayout(precision)

        commands = QHBoxLayout()
        self.install_button = QPushButton("Install / repair")
        self.install_button.setObjectName("primaryButton")
        self.install_button.clicked.connect(lambda: self._start("install"))
        commands.addWidget(self.install_button)
        self.cpu_button = QPushButton("Test CPU")
        self.cpu_button.clicked.connect(lambda: self._start("ready", device="cpu"))
        commands.addWidget(self.cpu_button)
        self.cuda_button = QPushButton("Test CUDA")
        self.cuda_button.clicked.connect(
            lambda: self._start("ready", device="cuda", compute_type=self.precision.currentData()))
        commands.addWidget(self.cuda_button)
        right.addLayout(commands)

        other = QHBoxLayout()
        self.default_button = QPushButton("Use as default")
        self.default_button.clicked.connect(self._default)
        other.addWidget(self.default_button)
        self.more_button = QPushButton("More actions")
        menu = QMenu(self.more_button)
        self.actions = {}
        for name, callback in (
            ("Verify integrity", lambda: self._start("verify")),
            ("Import local folder…", self._import),
            ("Discover legacy…", self._discover),
            ("Remove / unlink", self._remove),
        ):
            self.actions[name] = menu.addAction(name)
            self.actions[name].triggered.connect(callback)
        self.more_button.setMenu(menu)
        other.addWidget(self.more_button)
        right.addLayout(other)
        splitter.addWidget(details_panel)
        splitter.setSizes([420, 600])
        root.addWidget(splitter, 1)

        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        root.addWidget(self.progress)
        bottom = QHBoxLayout()
        self.status = QLabel("Downloads are explicit. Review model licenses before installing.")
        self.status.setWordWrap(True)
        bottom.addWidget(self.status, 1)
        self.cancel_button = QPushButton("Cancel operation")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._cancel)
        bottom.addWidget(self.cancel_button)
        root.addLayout(bottom)
        self._populate()

    def _availability(self, entry):
        state = self.service.status(entry)
        if state.state not in ("Installed", "Ready"):
            return state.state
        if entry.task == "stt" and any(
            self.service.is_ready(entry, device="cuda", compute_type=p)
            for p in ("float16", "int8_float16")
        ):
            return "Ready · CUDA"
        return "Ready · CPU" if state.ready else "Installed"

    def _populate(self, *_args):
        query = self.search.text().strip().lower()
        task = self.category.currentData()
        self.model_list.blockSignals(True)
        self.model_list.clear()
        self._items.clear()
        first = None
        selected = None
        for name, category in self._groups:
            if task is not None and category != task:
                continue
            entries = [
                model for model in descriptors(category)
                if not query or query in (model.label + " " + model.id + " " + model.engine).lower()
            ]
            if not entries:
                continue
            group = QTreeWidgetItem([name, ""])
            group.setFlags(group.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self.model_list.addTopLevelItem(group)
            for entry in entries:
                child = QTreeWidgetItem([entry.label, self._availability(entry)])
                child.setData(0, Qt.ItemDataRole.UserRole, entry.id)
                group.addChild(child)
                self._items[entry.id] = child
                first = first or child
                if entry.id == self._selected_id:
                    selected = child
            group.setExpanded(True)
        self.model_list.blockSignals(False)
        current = selected or first
        if current:
            self.model_list.setCurrentItem(current)
            self._selected_id = current.data(0, Qt.ItemDataRole.UserRole)
        else:
            self._selected_id = None
        self.refresh()

    def _selection(self, item, _previous):
        if item is not None and item.data(0, Qt.ItemDataRole.UserRole):
            self._selected_id = item.data(0, Qt.ItemDataRole.UserRole)
            self.refresh()

    def refresh(self, *_args):
        self.storage.setText(f"Storage: {self.service.root}")
        busy = self._worker is not None and self._worker.isRunning()
        for entry in descriptors():
            if entry.id in self._items:
                state = self._availability(entry)
                item = self._items[entry.id]
                item.setText(1, state)
                item.setForeground(1, QColor(
                    "#54c8a7" if state.startswith("Ready") else
                    "#efb866" if state == "Incomplete" else "#aab3c0"))
        if not self._selected_id:
            self.model_title.setText("No models match your search")
            self.state_label.clear()
            self.runtime_label.clear()
            self.details.clear()
            self._set_enabled(False)
            return
        entry = get_model(self._selected_id)
        state = self.service.status(entry)
        imported = entry.id in self.service.preferences().get("imports", {})
        locked = self.service.busy(entry)
        gpu_supported = entry.task == "stt" and "cuda" in entry.devices
        self.model_title.setText(entry.label)
        self.state_label.setText(f"Availability: {self._availability(entry)}")
        if gpu_supported:
            cpu = "Ready" if self.service.is_ready(entry, device="cpu") else "Not tested"
            gpu = "Ready" if self.service.is_ready(
                entry, device="cuda", compute_type=self.precision.currentData()) else "Not tested"
            self.runtime_label.setText(f"CPU (INT8): {cpu}     CUDA ({self.precision.currentData()}): {gpu}")
        else:
            self.runtime_label.setText(
                "CPU: " + ("Ready" if self.service.is_ready(entry) else "Not tested")
                + "     CUDA: Not supported by this model")
        size = f"{entry.expected_size_bytes / 2**20:.1f} MiB" if entry.expected_size_bytes else "Provided during download"
        self.details.setText(
            f"Engine: {entry.engine}\n"
            f"Source: {entry.source}\n"
            f"Revision: {entry.revision or 'publisher SHA-256'}\n"
            f"Languages: {', '.join(entry.languages)}\n"
            f"Devices: {', '.join(entry.devices)}\n"
            f"Size: {size}\n"
            f"License/access: {entry.license}\n{entry.access}\n\n"
            f"Path: {state.path}\n"
            f"{'External folder (unlink never deletes files). ' if imported else ''}{state.detail}"
        )
        self._set_enabled(not busy and not locked)
        self.install_button.setEnabled(not busy and not locked and
                                       entry.provider != "local-folder" and not imported)
        installed = state.state in ("Installed", "Ready")
        self.cpu_button.setEnabled(not busy and not locked and installed)
        self.cuda_button.setEnabled(not busy and not locked and installed and gpu_supported)
        self.precision.setEnabled(not busy and gpu_supported)
        self.actions["Verify integrity"].setEnabled(
            not busy and not locked and self.service.manifest_path(entry).is_file())
        self.cancel_button.setEnabled(busy)
        self.storage_button.setEnabled(not busy and not locked)

    def _set_enabled(self, enabled):
        for button in (self.install_button, self.cpu_button, self.cuda_button,
                       self.default_button, self.more_button, self.precision):
            button.setEnabled(enabled)

    def _start(self, operation, folder=None, *, device="cpu", compute_type=None):
        if self._worker and self._worker.isRunning():
            return
        if not self._selected_id:
            return
        model = get_model(self._selected_id)
        self._worker = ModelWorker(self.service, model, operation, folder,
                                   device=device, compute_type=compute_type, parent=self)
        self._worker.progress.connect(self._progress)
        self._worker.succeeded.connect(
            lambda: self.status.setText("Operation completed. Model status has been refreshed."))
        self._worker.failed.connect(self.status.setText)
        self._worker.finished.connect(self._finished)
        self.status.setText(f"Running {operation} for {model.label}…")
        self.progress.setRange(0, 0)
        self._worker.start()
        self.refresh()

    def _progress(self, stage, done, total, speed):
        self.progress.setRange(0, 1000 if total else 0)
        if total:
            self.progress.setValue(int(done / total * 1000))
        if total:
            self.status.setText(
                f"{stage} · {done / 2**20:.1f}/{total / 2**20:.1f} MiB · {speed / 2**20:.1f} MiB/s")
        else:
            self.status.setText(stage)

    def _finished(self):
        self.progress.setRange(0, 1000)
        self.modelsChanged.emit()
        self.refresh()

    def _cancel(self):
        if self._worker:
            self._worker.cancel.set()
            self.status.setText("Cancelling; waiting for current model operation…")

    def _import(self):
        folder = QFileDialog.getExistingDirectory(self, "Select complete model folder (linked, not copied)")
        if folder and QMessageBox.question(
            self, "Link model", "Files remain at this path. Moving the app will not move model weights. Continue?"
        ) == QMessageBox.StandardButton.Yes:
            self._start("import", Path(folder))

    def _discover(self):
        if not self._selected_id:
            return
        candidates = self.service.discover(get_model(self._selected_id))
        if not candidates:
            self.status.setText("No legacy model found. Use Import local folder.")
            return
        from PySide6.QtWidgets import QInputDialog
        choice, ok = QInputDialog.getItem(
            self, "Legacy models", "Link existing weights without moving them:",
            [str(path) for path in candidates], editable=False)
        if ok:
            self._start("import", Path(choice))

    def _default(self):
        if not self._selected_id:
            return
        self.service.set_default(get_model(self._selected_id))
        self.modelsChanged.emit()
        self.status.setText("Default model saved.")

    def _storage(self):
        folder = QFileDialog.getExistingDirectory(self, "Choose model storage")
        if not folder:
            return
        if QMessageBox.question(
            self, "Change model storage",
            "Existing weights stay where they are. Import to link them again. Continue?"
        ) != QMessageBox.StandardButton.Yes:
            return
        try:
            self.service.set_storage(Path(folder))
        except (OSError, ValueError, RuntimeError) as exc:
            self.status.setText(str(exc))
        self.modelsChanged.emit()
        self._populate()

    def _remove(self):
        if not self._selected_id:
            return
        if QMessageBox.question(
            self, "Remove model",
            "Delete managed weights or unlink the external folder? External files and projects are preserved."
        ) == QMessageBox.StandardButton.Yes:
            self._start("remove")

    def closeEvent(self, event):
        if self._worker and self._worker.isRunning():
            self._cancel()
            event.ignore()
        else:
            super().closeEvent(event)
