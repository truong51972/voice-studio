"""One serialized project queue. Panels never own inference processes."""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

from ..domain.speakers import AnalysisRecord
from ..projects import ProjectStore, _atomic_write
from ..task_runtime import TaskManager, TaskRequest


class ProjectSession(QObject):
    changed = Signal()
    resultReady = Signal(str, str, object)
    statusChanged = Signal(str)
    progressChanged = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.project: ProjectStore | None = None
        self.manager: TaskManager | None = None
        self.jobs: dict[str, AnalysisRecord | str] = {}
        self._stt_batches: dict[str, tuple[int, int]] = {}
        self.prepare_result = lambda task, media_id: None
        self.prepare_close = lambda: None
        self.validating = False
        self.timer = QTimer(self)
        self.timer.setInterval(120)
        self.timer.timeout.connect(self.poll)

    def open(self, project: ProjectStore) -> None:
        self.close()
        self.project = project
        self.manager = TaskManager(cpu_concurrency=1, root=project.directory / "cache" / "jobs")
        self.validating = bool(project.items)
        self.changed.emit()
        if project.items:
            self._submit("validate", {"media": [asdict(m) for m in project.items]})

    def _submit(self, action: str, inputs: dict, record: AnalysisRecord | None = None) -> str:
        if self.project is None or self.manager is None:
            raise ValueError("Create/open a project first")
        device = ("gpu" if action == "stt" and
                  inputs.get("options", {}).get("device") == "cuda" else "cpu")
        job = self.manager.submit(TaskRequest(kind="editor", inputs={
            "action": action, "project_directory": str(self.project.directory), **inputs,
        }, device=device))
        self.jobs[job] = record if record is not None else action
        if record is None:
            self.project.settings.setdefault('operations', []).append({"id": job, "action": action, "state": "queued", "error": None})
            self.project.save()
        self.timer.start()
        self.manager.poll()
        self.statusChanged.emit(f"Queued {action} · {len(self.jobs)} project jobs")
        return job

    def import_media(self, paths: list[str]) -> None:
        if self.validating or any(record == "import" for record in self.jobs.values() if isinstance(record, str)):
            raise ValueError("Wait for the current import/source check or cancel it first")
        self._submit("import", {"paths": paths})

    def relink(self, media_id: str, path: str) -> None:
        if self.jobs:
            raise ValueError("Wait for/cancel project jobs before relinking")
        job = self._submit("import", {"paths": [path]})
        self.jobs[job] = "relink:" + media_id

    def options_revision(self, task: str, options: dict) -> dict:
        """Small model file stamps invalidate cached runs; workers verify model bytes."""
        options = dict(options)
        if task in ("reference", "locator", "reconcile"):
            from ..profiles import get_inference_profile
            model = get_inference_profile(options["profile"])
            path = model.model_path
            options["model_revision"] = [model.model_sha256, path.stat().st_mtime_ns if path.is_file() else None]
        elif task == "diarization":
            folder = Path(options["model_directory"])
            options["model_revision"] = sorted([str(p.relative_to(folder)), p.stat().st_size, p.stat().st_mtime_ns]
                                                 for p in folder.rglob("*") if p.is_file()) if folder.is_dir() else []
        elif task == "stt":
            from ..model_registry import get_model, model_path
            folder = model_path(get_model(options["model_id"]))
            options["model_revision"] = sorted([str(p.relative_to(folder)), p.stat().st_size, p.stat().st_mtime_ns]
                                                 for p in folder.rglob("*") if p.is_file()) if folder.is_dir() else []
        return options

    def analyze(self, task: str, media_id: str, options: dict,
                progress_batch: tuple[int, int] | None = None, **extra) -> str | None:
        project = self.project
        if project is None:
            raise ValueError("Create/open a project first")
        if self.validating:
            raise ValueError("Wait for source validation to finish")
        item = project.get(media_id)
        if item.status in ("missing", "changed") or not Path(item.source).is_file():
            raise ValueError(item.error or "Relink the missing source first")
        stat = Path(item.source).stat()
        if item.mtime_ns and (item.mtime_ns != stat.st_mtime_ns or item.bytes != stat.st_size):
            raise ValueError("Source changed since import. Relink it to validate its fingerprint")
        options = self.options_revision(task, options)
        if task == 'reference':
            region = next(r for r in project.references if r.id == options['region_id'])
            project.validate_reference(region)
            diarization = project.latest_analysis(media_id, 'diarization')
            if diarization:
                extra['diarization_path'] = str(project.analysis_path(diarization.id))
        if task in ("locator", "reconcile"):
            options["reference_revision"] = [asdict(r) for r in project.references if r.state == "ready"]
        if task == 'reconcile':
            options["mapping_revision"] = project.cluster_mappings
        if task == "summary":
            options["transcript_revision"] = extra["document"]["revision"]
            digest = hashlib.sha256(json.dumps(extra["document"], sort_keys=True).encode()).hexdigest()
            options["transcript_snapshot"] = digest
            snapshot_path = project.directory / "cache" / f"review-snapshot-{digest}.json"
            _atomic_write(snapshot_path, extra.pop("document"))
            extra["document_path"] = str(snapshot_path)
        cached = project.cached_analysis(media_id, task, options)
        if cached:
            related_ids = {r.media_id for r in project.references if r.state == 'ready'} if task == 'locator' else set()
            related = [asdict(m) for m in project.items if m.id in related_ids]
            if task == 'reconcile' or (task == 'summary' and options.get('scope') == 'project'):
                related = [asdict(m) for m in project.items]
            job = self._submit('cached', {'target_path': item.source, 'fingerprint': item.fingerprint,
                'result_path': str(project.analysis_path(cached.id)),
                'related_sources': related})
            self.jobs[job] = 'cached:' + cached.id
            return job
        if any(isinstance(r, AnalysisRecord) and r.media_id == media_id and r.task == task
               and r.settings == options for r in self.jobs.values()):
            self.statusChanged.emit("This analysis is already queued")
            return None
        # Capture settings independently of subsequent speaker edits.
        import copy
        options = copy.deepcopy(options)
        record = project.queue_analysis(media_id, task, options)
        inputs = {"target_path": item.source, "fingerprint": item.fingerprint,
                  "media_kind": item.kind, "options": options, **extra}
        if task == "stt":
            inputs["source_duration"] = item.duration
        if task in ("locator", "reconcile"):
            inputs.update(media=[asdict(m) for m in project.items],
                          references=[asdict(r) for r in project.references], speakers=[asdict(s) for s in project.speakers])
        if task == "reconcile":
            clusters = []
            for source in project.items:
                analysis = project.latest_analysis(source.id, "diarization")
                if analysis:
                    turns = project.mapped_turns(analysis)
                    for speaker in {t["speaker_id"] for t in turns}:
                        clusters.append({"media_id": source.id, "speaker_id": speaker,
                                         "turns": [t for t in turns if t["speaker_id"] == speaker]})
            inputs["clusters"] = clusters
        try:
            job = self._submit(task, inputs, record)
        except Exception as exc:
            record.state, record.error = "failed", str(exc)
            project.save()
            raise
        if task == "stt":
            self._stt_batches[job] = progress_batch or (1, 1)
        self.changed.emit()
        return job

    def _emit_stt_progress(self) -> None:
        if self.manager is None or self.project is None:
            return
        pending = [(job, context, self.manager.snapshot(job)) for job, context in self.jobs.items()
                   if isinstance(context, AnalysisRecord) and context.task == "stt"]
        if not pending:
            return
        # Prefer the currently running source, never replace it with queued N+1.
        job, record, snapshot = next((row for row in pending if row[2].state == "running"), pending[0])
        source = self.project.get(record.media_id)
        index, count = self._stt_batches.get(job, (1, 1))
        self.progressChanged.emit({
            "state": snapshot.state, "stage": snapshot.stage, "error": snapshot.error,
            "filename": Path(source.source).name, "model": record.settings.get("model_id", ""),
            "device": record.settings.get("device", "cpu"),
            "processed_seconds": snapshot.processed_seconds,
            "total_seconds": snapshot.total_seconds or source.duration,
            "fraction": snapshot.progress, "elapsed_seconds": snapshot.elapsed_seconds,
            "eta_seconds": snapshot.eta_seconds,
            "source_index": index, "source_count": count,
        })

    def poll(self) -> None:
        if self.manager is None or self.project is None:
            return
        self.manager.poll()
        self._emit_stt_progress()
        for job_id, context in list(self.jobs.items()):
            snapshot = self.manager.snapshot(job_id)
            operation = next((entry for entry in self.project.settings.get('operations', []) if entry['id'] == job_id), None)
            if operation and operation['state'] != snapshot.state:
                operation['state'] = snapshot.state
                operation['error'] = snapshot.error
                self.project.save()
            if snapshot.state in ("queued", "running"):
                if snapshot.state == "running":
                    prefix = f'{Path(self.project.get(context.media_id).source).name} · {context.task} · ' if isinstance(context, AnalysisRecord) else ''
                    self.statusChanged.emit(prefix + snapshot.stage)
                if isinstance(context, AnalysisRecord) and context.state != snapshot.state:
                    context.state = snapshot.state
                    self.project.save()
                    self.changed.emit()  # Reflect running instead of stale queued source status.
                continue
            try:
                if snapshot.state != "completed":
                    raise ValueError(snapshot.error or "Cancelled")
                payload = self.manager.result(job_id)
                if context == "import":
                    self.project.import_assets(payload["assets"])
                elif isinstance(context, str) and context.startswith("relink:"):
                    self.prepare_result('relink', context.split(':', 1)[1])
                    self.project.relink_asset(context.split(":", 1)[1], payload["assets"][0])
                elif isinstance(context, str) and context.startswith('cached:'):
                    record = next(r for r in self.project.analyses if r.id == context.split(':', 1)[1])
                    if record.task in ('stt', 'diarization'):
                        self.prepare_result(record.task, record.media_id)
                    if record.task == 'stt':
                        item = self.project.get(record.media_id)
                        item.settings_key, item.status = record.id, 'completed'
                    elif record.task == 'reference':
                        region = next(r for r in self.project.references if r.id == record.settings['region_id'])
                        region.state, region.error = 'ready', None
                        region.model_revision = payload['model_revision']
                    self.project.save()
                    if record.task in ('stt', 'diarization'):
                        self.project.attribute_review(record.media_id)
                    self.resultReady.emit(record.task, record.media_id, payload)
                elif context == "validate":
                    for asset in payload["assets"]:
                        item = self.project.get(asset["id"])
                        if asset["status"] == "valid":
                            item.duration, item.kind = asset["duration"], asset["kind"]
                            item.bytes, item.mtime_ns = asset["bytes"], asset["mtime_ns"]
                            if item.status in ("missing", "changed"):
                                item.status = "completed" if self.project._result_path(item).is_file() else "pending"
                            item.error = None
                        else:
                            item.status, item.error = asset["status"], asset["error"]
                            for region in self.project.references:
                                if region.media_id == item.id:
                                    region.state, region.error = "invalid", asset["error"]
                    self.project.save()
                elif isinstance(context, AnalysisRecord):
                    if context.task in ('stt', 'diarization'):
                        self.prepare_result(context.task, context.media_id)
                    self.project.finish_analysis(context, payload)
                    self.resultReady.emit(context.task, context.media_id, payload)
                action = context.task if isinstance(context, AnalysisRecord) else context.split(':', 1)[0]
                self.statusChanged.emit('Reused cached inference' if action == 'cached' else f'Completed {action}')
            except Exception as exc:
                if isinstance(context, str) and context.startswith('cached:'):
                    record = next(r for r in self.project.analyses if r.id == context.split(':', 1)[1])
                    item = self.project.get(record.media_id)
                    if not Path(item.source).is_file() or 'Source content changed' in str(exc):
                        try:
                            self.prepare_result('source-changed', item.id)
                        except (OSError, ValueError) as save_error:
                            exc = ValueError(f'Could not save current edits: {save_error}. {exc}')
                        else:
                            item.status = 'missing' if not Path(item.source).is_file() else 'changed'
                            item.error = str(exc)
                    if record.task == 'reference':
                        region = next(r for r in self.project.references if r.id == record.settings['region_id'])
                        region.state, region.error = 'failed', str(exc)
                    self.project.save()
                if operation:
                    operation['state'], operation['error'] = ('cancelled' if snapshot.state == 'cancelled' else 'failed'), str(exc)
                    self.project.save()
                if isinstance(context, AnalysisRecord):
                    context.state = "cancelled" if snapshot.state == "cancelled" else "failed"
                    context.error = str(exc)
                    if context.task == "reference":
                        region = next(r for r in self.project.references if r.id == context.settings["region_id"])
                        region.state, region.error = "failed", str(exc)
                    self.project.save()
                self.statusChanged.emit(str(exc))
            finally:
                if isinstance(context, AnalysisRecord) and context.task == "stt":
                    index, count = self._stt_batches.pop(job_id, (1, 1))
                    source = self.project.get(context.media_id)
                    self.progressChanged.emit({
                        "state": snapshot.state, "stage": snapshot.stage, "error": snapshot.error,
                        "filename": Path(source.source).name, "model": context.settings.get("model_id", ""),
                        "device": context.settings.get("device", "cpu"),
                        "processed_seconds": snapshot.processed_seconds,
                        "total_seconds": snapshot.total_seconds or source.duration,
                        "fraction": snapshot.progress, "elapsed_seconds": snapshot.elapsed_seconds,
                        "eta_seconds": None, "source_index": index, "source_count": count,
                    })
                if context == "validate":
                    self.validating = False
                self.manager.acknowledge(job_id)
                del self.jobs[job_id]
                self.changed.emit()
        if not self.jobs:
            self.timer.stop()

    def cancel(self) -> None:
        if self.manager:
            for job in list(self.jobs):
                self.manager.cancel(job)
            self.poll()

    def close(self) -> None:
        if self.project is not None:
            self.prepare_close()
        self.timer.stop()
        self.cancel()
        if self.manager:
            self.manager.close()
        self.manager = None
        self.jobs.clear()
        self._stt_batches.clear()
        self.validating = False
