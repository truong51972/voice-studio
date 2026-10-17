"""Editor layout and view preferences; playback and jobs have separate controllers."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (QComboBox, QDoubleSpinBox, QFrame, QHBoxLayout, QLabel,
    QPushButton, QSlider, QSplitter, QStackedWidget, QTabWidget, QTextBrowser, QVBoxLayout, QWidget)

from .panels.stt import STTPanel
from .panels.projects import ProjectsPanel
from .panels.diarization import DiarizationPanel
from .panels.speakers import SpeakersPanel
from .panels.summary import SummaryPanel
from .widgets.media_player import PreviewVideoWidget
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
        self.diarization_panel = DiarizationPanel(self, session=self.session)
        self.summary_panel = SummaryPanel(self.stt_panel, self, session=self.session)
        self.projects_panel = ProjectsPanel(self.stt_panel, self, session=self.session)
        for text, callback in (('New', self.projects_panel._new), ('Open', self.projects_panel._open),
                               ('Recent', self.projects_panel._recent), ('Import media', self.projects_panel._add),
                               ('Save', self._save)):
            self._button(text, callback, toolbar)
        self.target_label = QLabel('No project')
        toolbar.addWidget(self.target_label, 1)
        self.scope = QComboBox()
        self.scope.addItems(['Selected source', 'Whole project'])
        toolbar.addWidget(self.scope)
        self.analyze_button = self._button('Auto Detect Speakers', self._start_analysis, toolbar)
        self.analyze_button.setObjectName('primaryButton')
        self.cancel_button = self._button('Cancel jobs', self.session.cancel, toolbar)
        self.models_button = self._button('Models', self._open_models, toolbar)
        root.addLayout(toolbar)
        self.pages = QStackedWidget()
        root.addWidget(self.pages, 1)
        picker = QWidget()
        picker_layout = QVBoxLayout(picker)
        picker_layout.addStretch()
        title = QLabel('<h1>Open your audio/video project</h1>')
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        picker_layout.addWidget(title)
        controls = QHBoxLayout()
        controls.addStretch()
        for text, callback in (('New project', self.projects_panel._new), ('Open project', self.projects_panel._open), ('Recent projects', self.projects_panel._recent)):
            self._button(text, callback, controls)
        controls.addStretch()
        picker_layout.addLayout(controls)
        self.picker_status = QLabel()
        self.picker_status.setWordWrap(True)
        self.picker_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        picker_layout.addWidget(self.picker_status)
        picker_layout.addStretch()
        self.pages.addWidget(picker)
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
        self.inspector_tabs.setMinimumWidth(350)
        self.speakers_panel = SpeakersPanel(self.session, self.diarization_panel, self)
        self.inspector_tabs.addTab(self.speakers_panel, 'Speakers')
        self.inspector_tabs.addTab(self._build_analysis_panel(), 'Analysis')
        self.inspector_tabs.addTab(self._build_segments_panel(), 'Segments')
        self.inspector_tabs.addTab(self.stt_panel, 'STT')
        self.project_info = QTextBrowser()
        self.inspector_tabs.addTab(self.project_info, 'Projects')
        raw_page = QWidget()
        raw_layout = QVBoxLayout(raw_page)
        self.raw_selector = QComboBox()
        self.raw_selector.currentIndexChanged.connect(self._show_raw)
        raw_layout.addWidget(self.raw_selector)
        self.raw_output = QTextBrowser()
        raw_layout.addWidget(self.raw_output)
        self.inspector_tabs.addTab(raw_page, 'Raw AI')
        self.inspector_tabs.addTab(self.summary_panel, 'Summary')
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
        self._button('Move earlier', lambda: self._move_clip(-1), commands)
        self._button('Move later', lambda: self._move_clip(1), commands)
        self.clip_in, self.clip_out = self._seconds_field(), self._seconds_field()
        commands.addWidget(QLabel('Trim source'))
        commands.addWidget(self.clip_in)
        commands.addWidget(self.clip_out)
        self._button('Apply trim', self._trim_clip, commands)
        commands.addWidget(QLabel('Zoom'))
        self.zoom = QSlider(Qt.Orientation.Horizontal)
        self.zoom.setRange(1, 64)
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
        self.timeline.seekRequested.connect(self._seek_project)
        self.timeline.selectionChanged.connect(self._timeline_selection)
        self.zoom.valueChanged.connect(lambda value: self.timeline.set_view(zoom=value))
        self.pan.valueChanged.connect(lambda value: self.timeline.set_view(pan=value / 1000.))
        timeline_layout.addWidget(self.timeline, 1)
        selection = QHBoxLayout()
        selection.addWidget(QLabel('Selection · source seconds'))
        self.selection_start, self.selection_end = self._seconds_field(), self._seconds_field()
        for field in (self.selection_start, self.selection_end):
            field.valueChanged.connect(self._selection_edited)
            selection.addWidget(field)
        self._button('Preview selection', self._preview_selection, selection)
        self._button('Add manual reference', self._manual_selection, selection)
        selection.addWidget(QLabel('Drag a source range · wheel zoom · Shift+wheel pan'), 1)
        timeline_layout.addLayout(selection)
        self.root_splitter.addWidget(timeline_page)
        self.root_splitter.setSizes([620, 260])
        editor_layout.addWidget(self.root_splitter)
        self.pages.addWidget(editor)
        self.projects_panel.mediaRequested.connect(self._select_media)
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

    def _build_menu(self):
        menu = self.menuBar().addMenu('File')
        for label, shortcut, callback in (('New project', 'Ctrl+N', self.projects_panel._new),
            ('Open project', 'Ctrl+O', self.projects_panel._open), ('Recent projects', '', self.projects_panel._recent),
            ('Import media', 'Ctrl+I', self.projects_panel._add), ('Save project', 'Ctrl+S', self._save),
            ('Export ordered report', '', self.projects_panel._export)):
            action = QAction(label, self)
            if shortcut:
                action.setShortcut(shortcut)
            action.triggered.connect(callback)
            menu.addAction(action)

    def _seconds_field(self):
        field = QDoubleSpinBox()
        field.setRange(0, 0)
        field.setDecimals(3)
        field.setSuffix('s')
        field.setMaximumWidth(110)
        return field

    def _help(self):
        browser = QTextBrowser()
        browser.setHtml('''<h2>Portable project editor</h2><p>New/Open/Recent Project → Import Media (multi-select). Sources remain external. Projects, results, reviews and caches live in .projects alongside the app (repository root in development). The portable folder must be writable; there is no AppData fallback.</p><p>One sequential source track: select, seek or play across clips; Move earlier/later and source trim change the project timeline without changing inference timestamps. Source and project clocks are labelled separately. Drag a range or type source seconds, then Preview selection.</p><h3>Speakers</h3><p>Auto Detect is the default. Explicitly install pyannote.audio 4 and a complete local Community-1 model; choose its folder in Speakers. No token or automatic cloud download is used. Missing/incompatible models produce actionable errors. Original overlap turns remain accessible in Raw AI; exclusive turns are used for transcript suggestions.</p><p>Manual references do not require pyannote. Select a clear single-voice source interval, preview it, choose/create a project speaker and Add manual reference. Silence/short intervals and known overlap are rejected. Without diarization, overlap cannot be ruled out automatically; audition the reference. Multiple intervals per speaker are supported. CAM++/ERes2NetV2 models are installed via Models. Match references finds similar sections; Compare project speakers proposes merges. Similarity is not identity verification or calibrated confidence. Every merge/split needs confirmation.</p><p>STT supports editable transcripts and TXT/SRT/Markdown/JSON exports. Whole project scope queues sources sequentially. Export all follows clip order/trims with source boundaries. Raw AI outputs and user edits stay separate. Cancel jobs/retry failed or interrupted tasks. Changing projects cancels the old queue before opening the new one.</p><h3>Backups</h3><p>Close the app and back up the entire .projects folder plus the original media before upgrading or moving. Extract upgrades into a new folder and copy .projects alongside the new executable; verify it opens before removing the old copy. Moving only the app does not move external recordings; use Relink. Exiting never deletes projects. Explicit deletion is by removing a backed-up project folder while the app is closed. Model/runtime cache paths are separate. Native Windows playback and real-model accuracy require release QA.</p>''')
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
        self.timeline.set_view(zoom=settings.get('timeline_zoom', self.zoom.value()), pan=settings.get('timeline_pan', self.pan.value() / 1000.))
        if settings.get('workspace_sizes'):
            self.workspace_splitter.setSizes(settings['workspace_sizes'])
        if settings.get('timeline_sizes'):
            self.root_splitter.setSizes(settings['timeline_sizes'])
