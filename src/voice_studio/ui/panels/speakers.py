"""Auto-first speakers, source references and explicitly confirmed proposals."""
from PySide6.QtCore import Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QColorDialog, QComboBox, QHBoxLayout, QInputDialog, QLabel, QListWidget,
                               QMessageBox, QPushButton, QTabWidget, QVBoxLayout, QWidget)

from .reference import ReferenceInput


class SpeakersPanel(QWidget):
    referenceRequested = Signal()
    compareRequested = Signal()
    edited = Signal()
    retryReferenceRequested = Signal(str)

    def __init__(self, session, diarization, parent=None):
        super().__init__(parent)
        self.session = session
        self.project = None
        layout = QVBoxLayout(self)
        self.mode = QComboBox()
        self.mode.addItems(["Auto Detect (default)", "Manual references", "Merge proposals"])
        layout.addWidget(self.mode)
        self.pages = QTabWidget()
        self.pages.tabBar().hide()
        self.mode.currentIndexChanged.connect(self.pages.setCurrentIndex)
        layout.addWidget(self.pages)
        auto = QWidget()
        auto_layout = QVBoxLayout(auto)
        auto_layout.setContentsMargins(0, 0, 0, 0)
        auto_layout.addWidget(diarization, 1)
        self.speaker = QComboBox()
        auto_layout.addWidget(self.speaker)
        actions = QHBoxLayout()
        for text, callback in (("Rename", self._rename), ('Color', self._color), ("Merge…", self._merge), ("Split cluster…", self._split)):
            button = QPushButton(text)
            button.clicked.connect(callback)
            actions.addWidget(button)
        auto_layout.addLayout(actions)
        self.pages.addTab(auto, "Auto")
        manual = QWidget()
        manual_layout = QVBoxLayout(manual)
        manual_layout.setContentsMargins(0, 0, 0, 0)
        self.reference = ReferenceInput()
        self.reference.saveRequested.connect(self.referenceRequested)
        manual_layout.addWidget(self.reference)
        self.references = QListWidget()
        self.references.setMinimumHeight(44)
        manual_layout.addWidget(self.references, 1)
        retry = QPushButton('Retry selected reference')
        retry.clicked.connect(lambda: self.retryReferenceRequested.emit(self.project.references[self.references.currentRow()].id)
                              if self.project and 0 <= self.references.currentRow() < len(self.project.references) else None)
        manual_layout.addWidget(retry)
        self.pages.addTab(manual, "Manual")
        proposals = QWidget()
        proposal_layout = QVBoxLayout(proposals)
        message = QLabel("Similarity suggests a possible match; it is not identity verification or calibrated confidence. Ambiguous candidates always need your review.")
        message.setWordWrap(True)
        proposal_layout.addWidget(message)
        compare = QPushButton("Compare project speakers")
        compare.clicked.connect(self.compareRequested)
        proposal_layout.addWidget(compare)
        self.proposals = QListWidget()
        proposal_layout.addWidget(self.proposals, 1)
        row = QHBoxLayout()
        for text, callback in (("Confirm merge…", self._confirm_proposal), ("Reject", self._reject_proposal)):
            button = QPushButton(text)
            button.clicked.connect(callback)
            row.addWidget(button)
        proposal_layout.addLayout(row)
        self.pages.addTab(proposals, "Proposals")
        self.status = QLabel("Auto Detect requires a locally installed optional Community-1 model. Manual matching does not require pyannote.")
        self.status.setWordWrap(True)
        self.status.setMaximumHeight(45)
        layout.addWidget(self.status)
        self._pending = []

    def refresh(self, project, media_id=None):
        self.project = project
        self.reference.set_project(project, media_id)
        selected = self.speaker.currentData()
        self.speaker.clear()
        self.references.clear()
        self.proposals.clear()
        self._pending = []
        if project is None:
            return
        names = {s.id: project.speaker(s.id).name for s in project.speakers}
        for speaker in project.speakers:
            if speaker.merged_into is None:
                self.speaker.addItem(f'{speaker.name} ({speaker.id[:6]})', speaker.id)
        self.speaker.setCurrentIndex(max(0, self.speaker.findData(selected)))
        for region in project.references:
            from pathlib import Path
            source = Path(project.get(region.media_id).source).name
            self.references.addItem(f"{names[region.speaker_id]} · {source} · {region.start:.3f}–{region.end:.3f}s · {region.state}"
                                    + (f" · {region.error}" if region.error else ""))
        for proposal in project.proposals:
            if proposal["state"] == "pending":
                self._pending.append(proposal)
                self.proposals.addItem(f"{names.get(proposal['left'], '?')} ↔ {names.get(proposal['right'], '?')} · "
                                       f"similarity {proposal['similarity']:.3f}" + (" · ambiguous" if proposal.get("ambiguous") else ""))

    def _rename(self):
        speaker_id = self.speaker.currentData()
        if not self.project or not speaker_id:
            return
        name, accepted = QInputDialog.getText(self, "Rename project speaker", "Label", text=self.project.speaker(speaker_id).name)
        if accepted and name.strip():
            self.project.rename_speaker(speaker_id, name)
            self.edited.emit()

    def _color(self):
        if not self.project or not self.speaker.currentData():
            return
        speaker = self.project.speaker(self.speaker.currentData())
        color = QColorDialog.getColor(QColor(speaker.color), self, 'Speaker track color')
        if color.isValid():
            speaker.color = color.name()
            self.project.save()
            self.edited.emit()

    def _confirm_merge(self, left, right):
        if self.session.jobs:
            self.status.setText("Wait for/cancel project jobs before changing speaker mappings")
            return
        a, b = self.project.speaker(left), self.project.speaker(right)
        if a.id == b.id:
            return
        answer = QMessageBox.question(self, "Confirm project-wide merge",
                                      f"Merge {b.name} into {a.name} across all sources and reviewed transcripts? Raw AI results remain available.")
        if answer == QMessageBox.StandardButton.Yes:
            self.project.merge_speakers(a.id, b.id)
            self.edited.emit()

    def _merge(self):
        if not self.project or self.speaker.currentData() is None:
            return
        others = [s for s in self.project.speakers if s.merged_into is None and s.id != self.speaker.currentData()]
        labels = [f"{s.name} ({s.id[:6]})" for s in others]
        choice, accepted = QInputDialog.getItem(self, "Merge project speakers", "Merge into selected speaker", labels, editable=False)
        if accepted and choice in labels:
            self._confirm_merge(self.speaker.currentData(), others[labels.index(choice)].id)

    def _split(self):
        if not self.project or self.session.jobs:
            self.status.setText("Wait for/cancel jobs before splitting a source cluster")
            return
        choices = []
        for source in self.project.items:
            record = self.project.latest_analysis(source.id, 'diarization')
            if record is None:
                continue
            for cluster, speaker in self.project.cluster_mappings.get(record.id, {}).items():
                if speaker == self.speaker.currentData():
                    from pathlib import Path
                    choices.append((record.id, cluster, f"{Path(source.source).name} · {cluster} · {record.id[:6]}"))
        labels = [c[2] for c in choices]
        choice, accepted = QInputDialog.getItem(self, "Split source cluster", "Give this cluster a separate project speaker", labels, editable=False)
        if accepted and choice in labels and QMessageBox.question(self, "Confirm split", "Create a separate speaker for this source cluster?") == QMessageBox.StandardButton.Yes:
            record_id, cluster, _ = choices[labels.index(choice)]
            self.project.split_cluster(record_id, cluster, f"Speaker {len(self.project.speakers) + 1}")
            self.edited.emit()

    def _confirm_proposal(self):
        row = self.proposals.currentRow()
        if 0 <= row < len(self._pending):
            proposal = self._pending[row]
            self._confirm_merge(proposal["left"], proposal["right"])

    def _reject_proposal(self):
        row = self.proposals.currentRow()
        if 0 <= row < len(self._pending):
            self._pending[row]["state"] = "rejected"
            self.project.save()
            self.edited.emit()
