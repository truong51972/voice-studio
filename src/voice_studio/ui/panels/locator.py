from __future__ import annotations

"""Known-speaker Locator inspector; a future task can supply other panels."""

from PySide6.QtCore import Slot
from PySide6.QtWidgets import (QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox,
                               QHeaderView, QLabel, QPushButton, QTableWidget,
                               QVBoxLayout, QWidget)

from ...config import DEFAULT_THRESHOLD
from ...profiles import DEFAULT_PROFILE_KEY, get_inference_profile
from ..constants import (DEFAULT_REFERENCE_SPEAKERS, MAX_REFERENCE_SPEAKERS,
                         PROFILE_CHOICES, SCENARIOS, SEGMENT_HEADERS)
from ..widgets.similarity_plot import SimilarityPlotWidget
from .reference import ReferenceInput


class LocatorPanelsMixin:
    """Build Locator panels while the main window owns all media/playback state."""

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
        from ...model_service import ModelService
        from ...model_catalog import get_model
        preferred = get_model(ModelService().default_id("locator")).profile_key
        self.profile.setCurrentIndex(max(0, self.profile.findData(preferred)))
        self.profile.currentIndexChanged.connect(self._apply_profile_default)

        self.threshold = QDoubleSpinBox()
        self.threshold.setRange(0.20, 0.90)
        self.threshold.setDecimals(2)
        self.threshold.setSingleStep(0.01)
        self.threshold.setValue(get_inference_profile(preferred).default_threshold)

        self.profile_help = QLabel(get_inference_profile(preferred).description)
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

    @Slot()
    def _apply_profile_default(self) -> None:
        profile = get_inference_profile(str(self.profile.currentData()))
        self.threshold.setValue(profile.default_threshold)
        self.profile_help.setText(profile.description)
