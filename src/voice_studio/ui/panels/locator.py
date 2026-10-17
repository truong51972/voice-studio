from __future__ import annotations

"""Known-speaker Locator inspector; a future task can supply other panels."""

from PySide6.QtCore import Slot
from PySide6.QtWidgets import (QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox,
                               QHeaderView, QLabel, QTableWidget,
                               QVBoxLayout, QWidget)

from ...config import DEFAULT_THRESHOLD
from ...profiles import DEFAULT_PROFILE_KEY, get_inference_profile
from ..constants import PROFILE_CHOICES, SCENARIOS, SEGMENT_HEADERS
from ..widgets.similarity_plot import SimilarityPlotWidget


class LocatorPanelsMixin:
    """Build Locator panels while the main window owns all media/playback state."""

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

    @Slot()
    def _apply_profile_default(self) -> None:
        profile = get_inference_profile(str(self.profile.currentData()))
        self.threshold.setValue(profile.default_threshold)
        self.profile_help.setText(profile.description)
