"""Editor layout and view preferences; playback and jobs have separate controllers."""
from PySide6.QtCore import Qt, QSignalBlocker
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (QComboBox, QDoubleSpinBox, QFrame, QHBoxLayout, QLabel,
    QPushButton, QSlider, QSplitter, QStackedWidget, QTabBar, QTabWidget, QTextBrowser,
    QVBoxLayout, QWidget)

from .panels.stt import STTPanel
from .panels.projects import ProjectsPanel
from .project_browser import ProjectBrowser
from .panels.diarization import DiarizationPanel
from .panels.speakers import SpeakersPanel
from .panels.summary import SummaryPanel
from .widgets.media_player import PreviewVideoWidget
from .widgets.stt_progress import STTProgressStrip
from .widgets.timeline import EditorTimelineWidget


class EditorLayoutMixin:
    def _button(self, text, callback, layout):
        button = QPushButton(text)
        button.clicked.connect(callback)
        layout.addWidget(button)
        return button

    def _build_analysis_tab(self):
        page = QWidget()
        root = QVBoxLayout(page)
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel('<b>Voice Studio</b>'))
        self.stt_panel = STTPanel(self, session=self.session)
        self.stt_progress = STTProgressStrip()
        self.stt_panel.layout().insertWidget(0, self.stt_progress)
        self.stt_progress.cancelRequested.connect(self.session.cancel)
        self.diarization_panel = DiarizationPanel(self, session=self.session)
        self.summary_panel = SummaryPanel(self.stt_panel, self, session=self.session)
        self.projects_panel = ProjectsPanel(self.stt_panel, self, session=self.session)
        self.target_label = QLabel('No project')
        toolbar.addWidget(self.target_label, 1)
        self.scope = QComboBox()
        self.scope.addItems(['Selected source', 'Whole project'])
        toolbar.addWidget(self.scope)
        self.analyze_button = self._button('Auto Detect Speakers', self._start_analysis, toolbar)
        # Speaker detection already lives in Speakers and Process; prioritize STT.
        self.analyze_button.hide()
        self.stt_panel.run_button.setObjectName('primaryButton')
        self.cancel_button = self._button('Cancel jobs', self.session.cancel, toolbar)
        self.cancel_button.hide()
        self.models_button = self._button('Models', self._open_models, toolbar)
        self.models_button.hide()
        root.addLayout(toolbar)
        self.pages = QStackedWidget()
        root.addWidget(self.pages, 1)
        self.project_browser = ProjectBrowser(self)
        self.project_browser.newRequested.connect(self.projects_panel._new)
        self.project_browser.openRequested.connect(self.projects_panel._open_folder)
        self.picker_status = self.project_browser.status
        self.pages.addWidget(self.project_browser)
        editor = QWidget()
        editor_layout = QVBoxLayout(editor)
        editor_layout.setContentsMargins(0, 0, 0, 0)
        self.root_splitter = QSplitter(Qt.Orientation.Vertical)
        self.root_splitter.setChildrenCollapsible(False)
        self.workspace_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.workspace_splitter.setChildrenCollapsible(False)
        self.projects_panel.setMinimumWidth(240)
        self.workspace_splitter.addWidget(self.projects_panel)
        preview = QFrame()
        preview.setObjectName('panel')
        preview_layout = QVBoxLayout(preview)
        self.preview_status = QLabel('Import sources to begin')
        self.preview_status.setWordWrap(True)
        preview_layout.addWidget(self.preview_status)
        self.video_widget = PreviewVideoWidget()
        self._player.setVideoOutput(self.video_widget)
        preview_layout.addWidget(self.video_widget, 1)
        transport = QHBoxLayout()
        self.play_button = self._button('▶', lambda: self._guard(self.playback.toggle), transport)
        self.time_label = QLabel('Project 0.0s · Source 0.0s')
        transport.addWidget(self.time_label)
        self.position_slider = QSlider(Qt.Orientation.Horizontal)
        self.position_slider.setRange(0, 0)
        self.position_slider.sliderMoved.connect(lambda ms: self._seek_project(ms / 1000.))
        transport.addWidget(self.position_slider, 1)
        preview_layout.addLayout(transport)
        self.workspace_splitter.addWidget(preview)
        self.inspector_tabs = QTabWidget()
        self.inspector_tabs.setObjectName("reviewInspector")
        self.inspector_tabs.setMinimumWidth(350)
        self.inspector_tabs.setDocumentMode(True)
        self.speakers_panel = SpeakersPanel(self.session, self.diarization_panel, self)
        # Everyday experience: the editable transcript is the primary surface.
        self.inspector_tabs.addTab(self.stt_panel, 'Transcript')
        self.inspector_tabs.addTab(self.speakers_panel, 'Speakers')
        self.project_info = QTextBrowser()
        raw_page = QWidget()
        raw_layout = QVBoxLayout(raw_page)
        self.raw_selector = QComboBox()
        self.raw_selector.currentIndexChanged.connect(self._show_raw)
        raw_layout.addWidget(self.raw_selector)
        self.raw_output = QTextBrowser()
        raw_layout.addWidget(self.raw_output)
        self._advanced_inspector_pages = {
            "analysis": (self._build_analysis_panel(), "Analysis"),
            "segments": (self._build_segments_panel(), "Segments"),
            "project": (self.project_info, "Project details"),
            "raw": (raw_page, "Raw AI"),
            "summary": (self.summary_panel, "Summary"),
        }
        for widget, title in self._advanced_inspector_pages.values():
            index = self.inspector_tabs.addTab(widget, title)
            self.inspector_tabs.setTabVisible(index, False)
        self.inspector_tabs.setTabsClosable(True)
        for index in (0, 1):
            self.inspector_tabs.tabBar().setTabButton(
                index, QTabBar.ButtonPosition.RightSide, None)
        self.inspector_tabs.tabCloseRequested.connect(self._close_inspector_tab)
        self.inspector_tabs.setCurrentWidget(self.stt_panel)
        self.workspace_splitter.addWidget(self.inspector_tabs)
        self.workspace_splitter.setSizes([330, 690, 425])
        self.workspace_splitter.setStretchFactor(1, 1)
        self.root_splitter.addWidget(self.workspace_splitter)
        timeline_page = QFrame()
        timeline_page.setObjectName('panel')
        timeline_layout = QVBoxLayout(timeline_page)
        commands = QHBoxLayout()
        self.summary_label = QLabel('Project source / speaker / transcript timeline')
        commands.addWidget(self.summary_label, 1)
        self.clip_in, self.clip_out = self._seconds_field(), self._seconds_field()
        commands.addWidget(QLabel('Trim source'))
        commands.addWidget(self.clip_in)
        commands.addWidget(self.clip_out)
        self._button('Apply trim', self._trim_clip, commands)
        commands.addWidget(QLabel('Zoom'))
        self.zoom = QSlider(Qt.Orientation.Horizontal)
        self.zoom.setRange(1, 128)
        self.zoom.setMaximumWidth(95)
        self.zoom.setValue(1)
        commands.addWidget(self.zoom)
        self.pan = QSlider(Qt.Orientation.Horizontal)
        self.pan.setRange(0, 1000)
        self.pan.setMaximumWidth(95)
        commands.addWidget(QLabel('Pan'))
        commands.addWidget(self.pan)
        timeline_layout.addLayout(commands)
        self.timeline = EditorTimelineWidget()
        self.timeline.setToolTip("Click: seek · Drag the red playhead/ruler: scrub · Drag canvas: pan when zoomed\nShift+drag: select range · Middle/right drag: pan · Wheel: cursor zoom · Shift+wheel: pan")
        self.timeline.seekRequested.connect(self._seek_project)
        self.timeline.selectionChangedClip.connect(self._timeline_clip_selection)
        self.timeline.viewChanged.connect(self._sync_timeline_controls)
        self.zoom.valueChanged.connect(lambda value: self.timeline.set_view(zoom=value, user=True))
        self.pan.valueChanged.connect(lambda value: self.timeline.set_view(pan=value / 1000., user=True))
        timeline_layout.addWidget(self.timeline, 1)
        selection = QHBoxLayout()
        selection.addWidget(QLabel('Selection · source seconds'))
        self.selection_start, self.selection_end = self._seconds_field(), self._seconds_field()
        for field in (self.selection_start, self.selection_end):
            field.valueChanged.connect(self._selection_edited)
            selection.addWidget(field)
        self._button('Preview selection', self._preview_selection, selection)
        self._button('Add manual reference', self._manual_selection, selection)
        selection.addWidget(QLabel('Shift+drag: range · Wheel: zoom · Drag: pan / scrub'), 1)
        timeline_layout.addLayout(selection)
        self.root_splitter.addWidget(timeline_page)
        self.root_splitter.setSizes([590, 290])
        editor_layout.addWidget(self.root_splitter)
        self.pages.addWidget(editor)
        self.projects_panel.clipRequested.connect(self._select_clip)
        self.projects_panel.clipOrderRequested.connect(self._reorder_clips)
        self.projects_panel.openRequested.connect(self._open_project_media)
        self.projects_panel.batchRequested.connect(lambda: self._run_stt(all_sources=True))
        self.stt_panel.startRequested.connect(self._run_stt)
        self.stt_panel.seekRequested.connect(self._seek_to_seconds)
        self.stt_panel.documentChanged.connect(self._save_project_review)
        self.diarization_panel.startRequested.connect(self._run_diarization)
        self.diarization_panel.seekRequested.connect(self._seek_to_seconds)
        self.diarization_panel.turnsReady.connect(self.stt_panel.apply_diarization)
        self.summary_panel.startRequested.connect(self._run_summary)
        self.speakers_panel.mode.currentIndexChanged.connect(lambda mode: self.analyze_button.setText('Match references' if mode == 1 else 'Auto Detect Speakers'))
        self.speakers_panel.referenceRequested.connect(self._add_reference)
        self.speakers_panel.compareRequested.connect(self._compare)
        self.speakers_panel.retryReferenceRequested.connect(self._retry_reference)
        self.speakers_panel.edited.connect(self._speaker_edited)
        reference = self.speakers_panel.reference
        reference.sourceSelected.connect(self._select_media)
        reference.selectionChanged.connect(lambda a, b: self._set_selection(a, b))
        reference.previewRequested.connect(lambda a, b: self._guard(self.playback.preview, self._clip_id, a, b))
        return page

    def _open_inspector_tool(self, key: str) -> None:
        """Show one advanced panel on demand without permanent tab clutter."""
        if key not in self._advanced_inspector_pages:
            raise ValueError("Unknown inspector tool")
        target = self._advanced_inspector_pages[key][0]
        for name, (widget, _) in self._advanced_inspector_pages.items():
            self.inspector_tabs.setTabVisible(
                self.inspector_tabs.indexOf(widget), name == key)
        self.inspector_tabs.setCurrentWidget(target)
        self.inspector_tabs.show()

    def _close_inspector_tab(self, index: int) -> None:
        if index < 2:
            return  # Transcript and Speakers are permanent navigation.
        self.inspector_tabs.setCurrentWidget(self.stt_panel)
        self.inspector_tabs.setTabVisible(index, False)

    def _sync_timeline_controls(self, zoom: float, pan: float) -> None:
        """Dragging or wheel zoom must update both toolbar sliders without loops."""
        with QSignalBlocker(self.zoom), QSignalBlocker(self.pan):
            self.zoom.setValue(round(zoom))
            self.pan.setValue(round(pan * 1000))

    def _seconds_field(self):
        field = QDoubleSpinBox()
        field.setRange(0, 0)
        field.setDecimals(3)
        field.setSuffix('s')
        field.setMaximumWidth(110)
        return field

    def _help(self):
        browser = QTextBrowser()
        browser.setHtml('''<h2>Portable project editor</h2><p>The right inspector keeps only <b>Transcript</b> and <b>Speakers</b> visible by default. Open optional tools through View → Advanced (Analysis, Segments, Project details, Raw AI), Settings → Inference defaults, or Process → Summarize. Optional panels appear temporarily and can be closed without losing their results.</p><p>New/Open/Recent Project → Import Media (multi-select). Sources remain external. Projects, results, reviews and caches live in .projects alongside the app (repository root in development). The portable folder must be writable; there is no AppData fallback.</p><p>One sequential source track: select, seek or play across clips; Move earlier/later and source trim change the project timeline without changing inference timestamps. Source and project clocks are labelled separately. Click to seek, drag the canvas to pan when zoomed, drag the playhead or ruler to scrub, Shift+drag to select a source interval (clamped to one clip). Wheel zooms around the pointer, Shift+wheel pans and Alt+wheel scrolls lanes. Type source seconds or Shift+drag then Preview selection.</p><h3>Speakers</h3><p>Auto Detect is the default. Default Windows packages include pyannote/Torch; all feature runtimes are installed by uv sync. Import a complete Community-1 folder through Settings → Models. See docs/diarization.md. No token or automatic cloud download is used. Missing/incompatible models produce actionable errors. Original overlap turns remain accessible in Raw AI; exclusive turns are used for transcript suggestions.</p><p>Manual references do not require pyannote. Select a clear single-voice source interval, preview it, choose/create a project speaker and Add manual reference. Silence/short intervals and known overlap are rejected. Without diarization, overlap cannot be ruled out automatically; audition the reference. Multiple intervals per speaker are supported. CAM++/ERes2NetV2 models are installed via Models. Match references finds similar sections; Compare project speakers proposes merges. Similarity is not identity verification or calibrated confidence. Every merge/split needs confirmation. New diarization runs refresh automatic transcript labels while preserving human speaker corrections and text edits. Each automatic assignment records its analysis ID. Uncertain automatic labels display Review speaker; split warnings persist until another analysis or a human correction.</p><p>STT supports editable transcripts and TXT/SRT/Markdown/JSON exports. Whole project scope queues sources sequentially. Export all follows clip order/trims with source boundaries. All selected export formats include boundary text only for fully contained timestamped words; untimed boundary text is omitted. Fully selected segments retain reviewed text. JSON includes only selected reviewed entries, without raw transcripts/history, and marks partial entries for review. Full-source JSON retains raw and edited views; back up .projects for a full archive. Raw AI outputs and user edits stay separate. Cancel jobs/retry failed or interrupted tasks. Changing projects cancels the old queue before opening the new one.</p><h3>Backups</h3><p>Close the app and back up the entire .projects folder plus the original media before upgrading or moving. Extract upgrades into a new folder and copy .projects alongside the new executable; verify it opens before removing the old copy. Moving only the app does not move external recordings; use Relink. Exiting never deletes projects. Explicit deletion is by removing a backed-up project folder while the app is closed. Model/runtime cache paths are separate. Native Windows playback and real-model accuracy require release QA.</p>''')
        return browser

    def _restore_ui(self, settings):
        for widget, key in ((self.profile, 'profile'), (self.stt_panel.model, 'stt_model'), (self.stt_panel.language, 'language')):
            if key in settings:
                widget.setCurrentIndex(max(0, widget.findData(settings[key])))
        self.threshold.setValue(settings.get('threshold', self.threshold.value()))
        self.diarization_panel.model_folder.setText(settings.get('diarization_model', ''))
        self.summary_panel.model.setText(settings.get('summary_model', ''))
        self.zoom.setValue(settings.get('zoom', 1))
        self.pan.setValue(settings.get('pan', 0))
        self.scope.setCurrentIndex(settings.get('scope', 0))
        self.speakers_panel.mode.setCurrentIndex(settings.get('speaker_mode', 0))
        self.stt_panel.vad.setChecked(settings.get('vad', True))
        self.stt_panel.words.setChecked(settings.get('word_timestamps', False))
        self.actions['subtitles'].setChecked(settings.get('show_subtitles', True))
        self.video_widget.overlay.set_show_subtitles(self.actions['subtitles'].isChecked())
        for widget, key in ((self.stt_panel.device, 'stt_device'),
                            (self.stt_panel.gpu_precision, 'stt_precision')):
            if key in settings:
                index = widget.findData(settings[key])
                if index >= 0:
                    widget.setCurrentIndex(index)
        self.timeline.set_view(zoom=settings.get('timeline_zoom', self.zoom.value()), pan=settings.get('timeline_pan', self.pan.value() / 1000.))
        if settings.get('workspace_sizes'):
            self.workspace_splitter.setSizes(settings['workspace_sizes'])
        if settings.get('timeline_sizes'):
            self.root_splitter.setSizes(settings['timeline_sizes'])
