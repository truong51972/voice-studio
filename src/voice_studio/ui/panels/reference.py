"""Manual references are source intervals, never uploaded/recorded enrollments."""
from PySide6.QtCore import QSignalBlocker, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout,
                               QGroupBox, QHBoxLayout, QLabel, QPushButton)


class ReferenceInput(QGroupBox):
    selectionChanged = Signal(float, float)
    sourceSelected = Signal(str)
    previewRequested = Signal(float, float)
    saveRequested = Signal()

    def __init__(self, parent=None):
        super().__init__("Source reference interval", parent)
        layout = QFormLayout(self)
        self.source = QComboBox()
        self.source.currentIndexChanged.connect(lambda: self.sourceSelected.emit(str(self.source.currentData() or '')))
        layout.addRow("Source", self.source)
        self.start = QDoubleSpinBox()
        self.end = QDoubleSpinBox()
        for field in (self.start, self.end):
            field.setDecimals(3)
            field.setRange(0, 0)
            field.setSuffix(" s")
            field.valueChanged.connect(lambda: self.selectionChanged.emit(self.start.value(), self.end.value()))
        interval = QHBoxLayout()
        interval.addWidget(self.start)
        interval.addWidget(QLabel('to'))
        interval.addWidget(self.end)
        layout.addRow("Source range", interval)
        self.speaker = QComboBox()
        self.speaker.setEditable(True)
        layout.addRow("Assign to", self.speaker)
        self.name_edit = self.speaker.lineEdit()
        self.name_edit.setStyleSheet('padding: 0; border: none; background: transparent;')
        self.name_edit.setPlaceholderText("Choose / type a speaker label")
        self.clean = QCheckBox("I previewed a single, clear voice")
        layout.addRow(self.clean)
        guidance = QLabel("3–10s of clean speech is guidance. Without diarization, check overlap by ear.")
        guidance.setWordWrap(True)
        layout.addRow(guidance)
        buttons = QHBoxLayout()
        self.preview_button = QPushButton("Preview interval")
        self.preview_button.clicked.connect(lambda: self.previewRequested.emit(self.start.value(), self.end.value()))
        self.save_button = QPushButton("Add manual reference")
        self.save_button.clicked.connect(self.saveRequested)
        buttons.addWidget(self.preview_button)
        buttons.addWidget(self.save_button)
        layout.addRow(buttons)

    def set_selection(self, start, end, duration):
        blockers = [QSignalBlocker(field) for field in (self.start, self.end)]
        self.start.setMaximum(duration or 0.)
        self.end.setMaximum(duration or 0.)
        self.start.setValue(start)
        self.end.setValue(end)
        del blockers
        self.clean.setChecked(False)

    def set_project(self, project, media_id=None):
        blocker = QSignalBlocker(self.source)
        self.source.clear()
        if project:
            from pathlib import Path
            for item in project.items:
                self.source.addItem(Path(item.source).name, item.id)
            self.source.setCurrentIndex(max(0, self.source.findData(media_id)))
        del blocker
        selected = self.speaker.currentData()
        typed = self.name_edit.text()
        self.speaker.clear()
        self.speaker.addItem("", None)
        if project:
            for speaker in project.speakers:
                if speaker.merged_into is None:
                    self.speaker.addItem(f'{speaker.name} ({speaker.id[:6]})', speaker.id)
        self.speaker.setCurrentIndex(max(0, self.speaker.findData(selected)))
        if selected is None:
            self.speaker.setEditText(typed)
