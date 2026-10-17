from __future__ import annotations

"""Project-first editor. Models and process dispatch belong to ProjectSession."""
import json
import os
import sys
from dataclasses import asdict, replace
from pathlib import Path

from PySide6.QtCore import QSignalBlocker, QTimer, QUrl
from PySide6.QtGui import QIcon
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import QApplication, QMainWindow, QTabWidget, QTableWidgetItem

from ..domain.timeline import map_time
from ..editor_tasks import waveform_path
from ..task_runtime import reconstruct_locator
from ..workspace import projects_directory
from .editor_layout import EditorLayoutMixin
from .actions import EditorActionsMixin
from .model_manager import ModelManagerDialog
from .panels.locator import LocatorPanelsMixin
from .playback import SequencePlayback
from .session import ProjectSession
from .resources import _resource_path
from .theme import APP_STYLESHEET
from .timecode import _fmt_time, _parse_timecode, milliseconds_to_seconds, seconds_to_milliseconds


class MainWindow(EditorActionsMixin, EditorLayoutMixin, LocatorPanelsMixin, QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Voice Studio · Editor')
        self.resize(1480, 940)
        self.setMinimumSize(1120, 760)
        self.setStyleSheet(APP_STYLESHEET)
        self.setWindowIcon(QIcon(str(_resource_path('voice-studio.png'))))
        self.session = ProjectSession(self)
        self._project_id = None
        self._clip_id = None
        self._target_path = None
        self._bundle = None
        self._current_fingerprint = None
        self._selection_restored = False
        self._outside_clip = False
        self._pending_review = False
        self._player = QMediaPlayer(self)
        self._audio_output = QAudioOutput(self)
        self._player.setAudioOutput(self._audio_output)
        self.playback = SequencePlayback(self._player, self)
        self.analysis_page = self._build_analysis_tab()
        self.setCentralWidget(self.analysis_page)
        self._build_actions()
        self.stt_panel.modelsRequested.connect(self._open_models)
        self.diarization_panel.modelsRequested.connect(self._open_models)
        self.session.changed.connect(self._refresh_project)
        self.session.resultReady.connect(self._result_ready)
        self.session.statusChanged.connect(self._status)
        self.session.prepare_result = self._before_result
        self.session.prepare_close = self._prepare_close
        self.stt_panel.editingStarted.connect(self.playback.pause)
        self.playback.clipChanged.connect(self._clip_changed)
        self.playback.positionChanged.connect(self._project_position)
        self.playback.error.connect(self._status)
        self.playback.previewOutsideClip.connect(lambda outside: setattr(self, '_outside_clip', outside))
        self._player.playbackStateChanged.connect(self._on_playback_state)
        self._player.durationChanged.connect(self._on_player_duration)
        try:
            root = projects_directory()
            self.picker_status.setText(f'Portable projects: {root}\nMedia stay external; moving the app does not move original recordings.')
        except OSError as exc:
            self.picker_status.setText(str(exc))


    def _guard(self, callback, *args, **kwargs):
        try:
            return callback(*args, **kwargs)
        except (ValueError, OSError, KeyError, StopIteration, TypeError, RuntimeError) as exc:
            self._status(str(exc))
            return None

    def _status(self, text):
        self.statusBar().showMessage(text)
        self.preview_status.setText(text)
        self.picker_status.setText(text)
        self.speakers_panel.status.setText(text)
        self.stt_panel.status.setText(text)
        self.summary_panel.status.setText(text)
        for label in (self.preview_status, self.speakers_panel.status, self.stt_panel.status, self.summary_panel.status):
            label.setToolTip(text)
        self.cancel_button.setEnabled(bool(self.session.jobs))
        for panel in (self.stt_panel, self.diarization_panel, self.summary_panel):
            panel.cancel_button.setEnabled(bool(self.session.jobs))

    def _refresh_project(self):
        project = self.session.project
        if project is None:
            return
        if self._project_id != project.id:
            self._project_id = project.id
            self._clip_id = self._target_path = None
            self._current_fingerprint = None
            self._selection_restored = False
            self._outside_clip = False
            self._pending_review = False
            self.playback.set_project(project)
            self.stt_panel.set_media(None)
            self.diarization_panel.set_media(None)
            self.summary_panel.reset()
            self._bundle = None
            self.video_widget.overlay.set_bundle(None)
            self.timeline.set_bundle(None)
            self._project_position(0., 0.)
            self.pages.setCurrentIndex(1)
            self._restore_ui(project.settings.get('ui', {}))
        self.target_label.setText(project.name)
        item = self._current_item()
        self.speakers_panel.refresh(project, item.id if item else None)
        details = [f'{project.name}\n{project.directory}\nExternal sources: {len(project.items)}\n']
        details.extend(f'{r.task} · {Path(project.get(r.media_id).source).name} · {r.state}' + (f' · {r.error}' if r.error else '') for r in project.analyses)
        details.extend(f"{op['action']} · {op['state']}" + (f" · {op['error']}" if op.get('error') else '') for op in project.settings.get('operations', []))
        self.project_info.setPlainText('\n'.join(details))
        selected = self.raw_selector.currentData()
        blocker = QSignalBlocker(self.raw_selector)
        self.raw_selector.clear()
        for record in project.analyses:
            if record.state == 'completed':
                self.raw_selector.addItem(f'{Path(project.get(record.media_id).source).name} · {record.task} · {record.id[:6]}', record.id)
        self.raw_selector.setCurrentIndex(max(0, self.raw_selector.findData(selected)))
        del blocker
        self._show_raw()
        self._render_timeline()
        if item and item.status in ('missing', 'changed'):
            self.playback.player.pause()
            self.stt_panel.set_media(None)
            self.diarization_panel.set_media(None)
            self.video_widget.overlay.set_bundle(None)
            self.video_widget.overlay.set_turns([], {})
            self.preview_status.setText(item.error or 'Relink source before analysis')
        elif item and (self._current_fingerprint != item.fingerprint or self._target_path != item.source):
            clip_id = self._clip_id
            self._clip_id = None
            self.stt_panel.set_media(None)
            self.diarization_panel.set_media(None)
            self.playback.player.setSource(QUrl())
            self._guard(self.playback.select_clip, clip_id)
        if self._clip_id is None and project.clips and not self.session.validating:
            selected = project.settings.get('ui', {}).get('clip_id')
            clip = next((c for c in project.clips if c.id == selected), project.clips[0])
            self._guard(self.playback.select_clip, clip.id)
        self.cancel_button.setEnabled(bool(self.session.jobs))

    def _render_timeline(self):
        project = self.session.project
        try:
            mapping = project.timeline()
        except ValueError as exc:
            self.timeline.set_project_data(None, [], [])
            self.summary_label.setText(str(exc))
            return
        sources, annotations = [], []
        for clip in project.clips:
            item = project.get(clip.media_id)
            peaks_file = waveform_path(project.directory, item.fingerprint)
            try:
                peaks = json.loads(peaks_file.read_text())['peaks'] if peaks_file.is_file() else []
            except (ValueError, KeyError, OSError):
                peaks = []
            label = Path(item.source).name + (f' [{item.status}]' if item.status in ('missing', 'changed') else '')
            sources.append({'clip': clip, 'name': label, 'duration': item.duration, 'peaks': peaks})
            if item.status in ('missing', 'changed'):
                continue
            def annotate(start, end, lane, text, color='#36c5d8', overlap=False):
                start, end = max(start, clip.source_in), min(end, clip.end(item.duration))
                if end > start:
                    annotations.append({'start': map_time(clip, mapping.starts[clip.id], start, item.duration, to_source=False),
                                        'end': map_time(clip, mapping.starts[clip.id], end, item.duration, to_source=False),
                                        'lane': lane, 'text': text, 'color': color, 'overlap': overlap})
            diarization = project.latest_analysis(item.id, 'diarization')
            if diarization:
                for turn in project.mapped_turns(diarization):
                    speaker = project.speaker(turn['speaker_id']) if turn['speaker_id'] else None
                    name = speaker.name if speaker else 'Anonymous'
                    annotate(turn['start'], turn['end'], name, name, speaker.color if speaker else '#777777', turn['overlap'])
            if item.status == 'completed':
                for entry in project.review(item.id).edited:
                    annotate(entry.start, entry.end, 'Transcript', entry.text, '#8fa4bd')
            locator = project.latest_analysis(item.id, 'locator')
            if locator:
                for result in project.result(locator)['results']:
                    speaker = project.speaker(result['key'])
                    for segment in result['segments']:
                        annotate(segment['start'], segment['end'], 'Match ' + speaker.name, speaker.name, speaker.color)
        self.timeline.set_project_data(mapping, sources, annotations)
        self.position_slider.setMaximum(round(mapping.duration * 1000))
        self.summary_label.setText(f'{len(project.clips)} clips · project {_fmt_time(mapping.duration)}')

    def _current_clip(self):
        project = self.session.project
        return next((c for c in project.clips if c.id == self._clip_id), None) if project else None

    def _current_item(self):
        clip = self._current_clip()
        return self.session.project.get(clip.media_id) if clip else None

    def _select_media(self, media_id):
        project = self.session.project
        if project and media_id:
            if self.session.validating:
                self._status('Checking source fingerprints; select media once validation finishes')
                return
            item = project.get(media_id)
            if item.status in ('missing', 'changed'):
                self._status(item.error or 'Relink the source first')
                return
            clip = next((c for c in project.clips if c.media_id == media_id), None)
            if clip:
                self._guard(self.playback.select_clip, clip.id)

    def _clip_changed(self, clip_id):
        changed = clip_id != self._clip_id
        self._clip_id = clip_id
        item, clip = self._current_item(), self._current_clip()
        self._target_path = item.source
        self._current_fingerprint = item.fingerprint
        self.stt_panel.set_media(item.source)
        self.diarization_panel.set_media(item.source)
        if changed:
            self.summary_panel.reset()
        self.projects_panel.active_id = item.id
        self.projects_panel.table.selectRow(next(i for i, source in enumerate(self.session.project.items) if source.id == item.id))
        self.speakers_panel.refresh(self.session.project, item.id)
        for field, value in ((self.clip_in, clip.source_in), (self.clip_out, clip.end(item.duration))):
            field.setMaximum(item.duration)
            field.setValue(value)
        if changed:
            saved = self.session.project.settings.get('ui', {})
            selection = saved.get('selection') if not self._selection_restored and saved.get('clip_id') == clip_id else None
            if selection and 0 <= selection[0] < selection[1] <= item.duration:
                self._set_selection(*selection)
            else:
                self._set_selection(clip.source_in, min(clip.end(item.duration), clip.source_in + 5.))
            self._selection_restored = True
        self._load_current_results()

    def _load_current_results(self, *, reload_review=True):
        project, item = self.session.project, self._current_item()
        if not item:
            return
        self.stt_panel.speaker_names = {s.id: project.speaker(s.id).name for s in project.speakers}
        if item.status == 'completed' and reload_review:
            document = project.review(item.id)
            self.projects_panel._active_document = document
            self.projects_panel._active_review_key = item.settings_key
            self.stt_panel.load_document(document)
        diarization = project.latest_analysis(item.id, 'diarization')
        if diarization:
            raw = project.result(diarization)
            mapped = {**raw, 'turns': project.mapped_turns(diarization), 'exclusive_turns': project.mapped_turns(diarization, exclusive=True)}
            self.diarization_panel._show(mapped)
            self.video_widget.overlay.set_turns(mapped['turns'], self.stt_panel.speaker_names)
        else:
            self.video_widget.overlay.set_turns([], {})
        locator = project.latest_analysis(item.id, 'locator')
        self._bundle = None
        if locator:
            self._bundle = reconstruct_locator(project.result(locator))
            self._bundle = replace(self._bundle, results=[replace(r, name=project.speaker(r.key).name) for r in self._bundle.results])
        self.video_widget.overlay.set_bundle(self._bundle)
        self.similarity_plot.set_bundle(self._bundle, self.threshold.value())
        self._populate_segments(self._bundle)
        summary = project.latest_analysis(item.id, 'summary')
        if summary:
            self.summary_panel._show(project.result(summary))

    def _open_project_media(self, source, document):
        self.stt_panel.load_document(document)
        self.projects_panel._active_document = document
        if self.session.project and self.projects_panel.active_id:
            self.projects_panel._active_review_key = self.session.project.get(self.projects_panel.active_id).settings_key

    def _targets(self, all_sources=False):
        project = self.session.project
        if project is None:
            raise ValueError('Create/open a project and import sources first')
        if all_sources or self.scope.currentIndex() == 1:
            return [item.id for item in project.items if item.status not in ('missing', 'changed')]
        item = self._current_item()
        if item is None:
            raise ValueError('Select an imported source first')
        return [item.id]

    def _start_analysis(self):
        if self.speakers_panel.mode.currentIndex() == 1:
            options = {'profile': str(self.profile.currentData()), 'threshold': self.threshold.value(), 'scenario': self.scenario.currentText()}
            self._guard(self._queue_targets, 'locator', options)
        else:
            self._run_diarization()

    def _queue_targets(self, task, options, all_sources=False):
        if task in ('locator', 'stt', 'diarization'):
            from ..model_catalog import descriptors, get_model, default_model
            from ..model_service import ModelService
            if task == 'locator':
                model = next(entry for entry in descriptors('locator') if entry.profile_key == options['profile'])
            elif task == 'stt':
                model = get_model(options['model_id'])
            else:
                model = default_model('diarization')
            blockers = ModelService().preflight(
                model, device=options.get('device', 'cpu'),
                compute_type=options.get('compute_type') if task == 'stt' else None)
            if blockers:
                self._status('; '.join(blockers))
                self._open_models(model.id)
                return
        targets = self._targets(all_sources)
        for index, media_id in enumerate(targets, start=1):
            self.session.analyze(task, media_id, options,
                                 progress_batch=(index, len(targets)) if task == "stt" else None)

    def _run_diarization(self):
        from ..model_catalog import default_model
        from ..model_service import ModelService
        model = default_model('diarization')
        folder = ModelService().path(model)
        self._guard(self._queue_targets, 'diarization', {'model_directory': str(folder)})

    def _run_stt(self, all_sources=False):
        self._guard(self._queue_targets, 'stt', self.projects_panel._options(), all_sources)

    def _run_summary(self):
        def run():
            model = self.summary_panel.model.text().strip()
            if not model:
                raise ValueError('Enter an already installed local Ollama model')
            if self.scope.currentIndex() == 1:
                targets = self._targets()
                if not targets:
                    raise ValueError('Import and transcribe sources before a project summary')
                document = self.session.project.summary_document()
                sources = [{'source': item.source, 'fingerprint': item.fingerprint} for item in self.session.project.items]
                self.session.analyze('summary', targets[0], {'model': model, 'scope': 'project'},
                                     document=document.serialize(), source_fingerprints=sources)
                return
            for media_id in self._targets():
                document = self.session.project.export_document(media_id)
                self.session.analyze('summary', media_id, {'model': model}, document=document.serialize())
        self._guard(run)

    def _ready_locator(self):
        from ..model_catalog import descriptors
        from ..model_service import ModelService
        model = next(entry for entry in descriptors("locator") if entry.profile_key == self.profile.currentData())
        errors = ModelService().preflight(model)
        if errors:
            self._status("; ".join(errors))
            self._open_models(model.id)
            return False
        return True

    def _add_reference(self):
        def run():
            reference = self.speakers_panel.reference
            project, item = self.session.project, self._current_item()
            if not item:
                raise ValueError('Select a source first')
            if not self._ready_locator():
                return
            if not reference.clean.isChecked():
                raise ValueError('Preview the interval and confirm it contains one clear voice')
            speaker_id = reference.speaker.currentData()
            if reference.speaker.currentText() != reference.speaker.itemText(reference.speaker.currentIndex()):
                speaker_id = None
            start, end = reference.start.value(), reference.end.value()
            # Validate before creating a new project label.
            from ..domain.speakers import ReferenceRegion
            project.validate_reference(ReferenceRegion('preview', '', item.id, start, end, item.fingerprint))
            if end - start < 1.:
                raise ValueError('Select at least 1 second; usually 3–10s of clean speech is useful')
            if not speaker_id:
                speaker_id = project.create_speaker(reference.name_edit.text()).id
            region = project.add_reference(speaker_id, item.id, start, end)
            self.session.analyze('reference', item.id, {'profile': str(self.profile.currentData()), 'region_id': region.id},
                                 region=asdict(region), source=asdict(item))
            self._refresh_project()
        self._guard(run)

    def _compare(self):
        def run():
            targets = self._targets()
            if not targets:
                raise ValueError('Import sources and detect speakers first')
            if not self._ready_locator():
                return
            self.session.analyze('reconcile', targets[0], {'profile': str(self.profile.currentData()), 'threshold': self.threshold.value()})
        self._guard(run)

    def _retry_reference(self, region_id):
        def run():
            project = self.session.project
            region = next(r for r in project.references if r.id == region_id)
            source = project.get(region.media_id)
            if region.fingerprint != source.fingerprint:
                raise ValueError('Source changed; select a new reference interval')
            project.validate_reference(region)
            if not self._ready_locator():
                return
            job = self.session.analyze('reference', source.id, {'profile': str(self.profile.currentData()), 'region_id': region.id},
                                 region=asdict(region), source=asdict(source))
            if job:
                region.state, region.error = 'pending', None
                project.save()
            self._refresh_project()
        self._guard(run)

    def _result_ready(self, task, media_id, payload):
        item = self._current_item()
        if item and item.id == media_id:
            if task in ('stt', 'diarization') and QApplication.activeModalWidget() is not None:
                self._pending_review = True
                QTimer.singleShot(50, self._refresh_pending_review)
            else:
                self._load_current_results(reload_review=task in ('stt', 'diarization'))
        if task == 'summary' and payload.get('scope') == 'project':
            self.summary_panel._show(payload)
        self._render_timeline()

    def _before_result(self, task, media_id):
        item = self._current_item()
        if item and item.id == media_id:
            self.stt_panel.commit_edit()
            self.projects_panel.save_active_review(self.stt_panel.document)

    def _refresh_pending_review(self):
        if not self._pending_review:
            return
        if QApplication.activeModalWidget() is not None:
            QTimer.singleShot(50, self._refresh_pending_review)
            return
        self._pending_review = False
        item = self._current_item()
        if item:
            self.session.project.attribute_review(item.id)
            self._load_current_results()

    def _speaker_edited(self):
        self._refresh_project()
        self._load_current_results()

    def _save_project_review(self):
        try:
            self.projects_panel.save_active_review(self.stt_panel.document)
        except (OSError, ValueError) as exc:
            self.playback.pause()
            self._status(f'Could not save transcript edits: {exc}')
        if self.session.project:
            self._render_timeline()

    def _set_selection(self, start, end):
        item = self._current_item()
        if not item:
            return
        blockers = [QSignalBlocker(f) for f in (self.selection_start, self.selection_end)]
        for field, value in ((self.selection_start, start), (self.selection_end, end)):
            field.setMaximum(item.duration or 0.)
            field.setValue(value)
        del blockers
        self.speakers_panel.reference.set_selection(start, end, item.duration)
        self.stt_panel.export_range = (start, end)
        self.timeline.set_selection(self._clip_id, start, end)

    def _selection_edited(self):
        self._set_selection(self.selection_start.value(), self.selection_end.value())

    def _timeline_selection(self, media_id, start, end):
        item = self._current_item()
        if not item or item.id != media_id:
            self._select_media(media_id)
        self._set_selection(start, end)

    def _manual_selection(self):
        self.inspector_tabs.setCurrentIndex(0)
        self.speakers_panel.mode.setCurrentIndex(1)

    def _preview_selection(self):
        self._guard(self.playback.preview, self._clip_id, self.selection_start.value(), self.selection_end.value())

    def _move_clip(self, delta):
        def move():
            project = self.session.project
            identifiers = [c.id for c in project.clips]
            index = identifiers.index(self._clip_id)
            target = index + delta
            if 0 <= target < len(identifiers):
                identifiers[index], identifiers[target] = identifiers[target], identifiers[index]
                project.reorder_clips(identifiers)
                self._render_timeline()
        self._guard(move)

    def _trim_clip(self):
        def trim():
            self.session.project.trim_clip(self._clip_id, self.clip_in.value(), self.clip_out.value())
            self._render_timeline()
            self.playback.select_clip(self._clip_id)
        self._guard(trim)

    def _seek_project(self, seconds):
        if self.session.project:
            self._guard(self.playback.seek_project, seconds)

    def _seek_to_seconds(self, seconds):
        if self.session.project:
            self._guard(self.playback.seek_source, seconds)
        else:
            self._player.setPosition(seconds_to_milliseconds(seconds))
            self._player.pause()

    def _project_position(self, project_seconds, source_seconds):
        blocker = QSignalBlocker(self.position_slider)
        self.position_slider.setValue(round(project_seconds * 1000))
        del blocker
        project_label = '— (source preview)' if self._outside_clip else _fmt_time(project_seconds)
        self.time_label.setText(f'Project {project_label} · Source {_fmt_time(source_seconds)}')
        self.timeline.set_position_seconds(project_seconds)
        self.video_widget.overlay.set_position(source_seconds)
        self.stt_panel.set_playhead(source_seconds)

    def _on_player_position(self, milliseconds):
        # Compatibility for callers with a single source clock.
        seconds = milliseconds_to_seconds(milliseconds)
        self._project_position(seconds, seconds)

    def _on_player_duration(self, milliseconds):
        if self.session.project is None:
            self.position_slider.setMaximum(max(0, milliseconds))
            self.timeline.set_duration_seconds(milliseconds_to_seconds(milliseconds))

    def _on_playback_state(self, state):
        self.play_button.setText('❚❚' if state == QMediaPlayer.PlaybackState.PlayingState else '▶')

    def _populate_segments(self, bundle):
        rows = [(r.name, _fmt_time(s.start), _fmt_time(s.end), f'{s.max_score:.3f}')
                for r in bundle.results for s in r.segments] if bundle else []
        self.segment_table.setRowCount(len(rows))
        for row, values in enumerate(rows):
            for column, value in enumerate(values):
                self.segment_table.setItem(row, column, QTableWidgetItem(value))

    def _seek_segment(self, row, column):
        item = self.segment_table.item(row, 1)
        if item:
            self._seek_to_seconds(_parse_timecode(item.text()))

    def _show_raw(self):
        project = self.session.project
        if project and self.raw_selector.currentData():
            self._guard(lambda: self.raw_output.setPlainText(project.analysis_path(self.raw_selector.currentData()).read_text(encoding='utf-8')))
        else:
            self.raw_output.clear()


    def _save(self):
        try:
            self._save_project()
        except (OSError, ValueError) as exc:
            self.playback.pause()
            self._status(f'Could not save project: {exc}')

    def _prepare_close(self):
        self.playback.pause()
        self._save_project()

    def _save_project(self):
        project = self.session.project
        if project is None:
            return
        self.stt_panel.commit_edit()
        self.projects_panel.save_active_review(self.stt_panel.document)
        project.settings['ui'] = {'clip_id': self._clip_id, 'profile': self.profile.currentData(),
            'threshold': self.threshold.value(), 'stt_model': self.stt_panel.model.currentData(),
            'language': self.stt_panel.language.currentData(), 'diarization_model': self.diarization_panel.model_folder.text(),
            'summary_model': self.summary_panel.model.text(), 'zoom': self.zoom.value(), 'pan': self.pan.value(),
            'timeline_zoom': self.timeline._zoom, 'timeline_pan': self.timeline._pan,
            'scope': self.scope.currentIndex(), 'speaker_mode': self.speakers_panel.mode.currentIndex(),
            'vad': self.stt_panel.vad.isChecked(), 'word_timestamps': self.stt_panel.words.isChecked(),
            'stt_device': self.stt_panel.device.currentData(),
            'stt_precision': self.stt_panel.gpu_precision.currentData(),
            'selection': [self.selection_start.value(), self.selection_end.value()],
            'workspace_sizes': self.workspace_splitter.sizes(), 'timeline_sizes': self.root_splitter.sizes()}
        project.save()
        self._status('Project saved')

    def _open_models(self, model_id=None):
        dialog = ModelManagerDialog(self, model_id=model_id if isinstance(model_id, str) else None)
        dialog.modelsChanged.connect(self.stt_panel.refresh_models)
        dialog.modelsChanged.connect(self.diarization_panel.refresh_models)
        dialog.exec()
        self.stt_panel.refresh_models()
        self.diarization_panel.refresh_models()

    def closeEvent(self, event):
        try:
            self.session.close()
        except (OSError, ValueError) as exc:
            self._status(f"Could not save project: {exc}")
            event.ignore()
            return
        self._stop_actions()
        self.playback.player.stop()
        super().closeEvent(event)


def create_application(argv: list[str] | None = None) -> QApplication:
    if sys.platform == 'linux':
        os.environ.setdefault('QT_AUDIO_BACKEND', 'pulseaudio')
    existing = QApplication.instance()
    if existing is not None:
        return existing
    app = QApplication(argv if argv is not None else sys.argv)
    app.setWindowIcon(QIcon(str(_resource_path('voice-studio.png'))))
    return app


def build_app() -> MainWindow:
    return MainWindow()
