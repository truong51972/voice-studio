"""One player and one sequential project clock; Qt milliseconds stop here."""
from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtMultimedia import QMediaPlayer


class SequencePlayback(QObject):
    clipChanged = Signal(str)
    positionChanged = Signal(float, float)
    error = Signal(str)
    previewOutsideClip = Signal(bool)

    def __init__(self, player, parent=None):
        super().__init__(parent)
        self.player = player
        self.project = None
        self.clip_id = None
        self._pending = None
        self._resume = False
        self._preview_end = None
        self.player.positionChanged.connect(self._position)
        self.player.mediaStatusChanged.connect(self._media_status)
        self.player.errorOccurred.connect(lambda _code, message: self.error.emit(
            "Playback failed: " + (message or "Qt Multimedia could not decode this source")
            + ". Check the media codec and Qt multimedia runtime; analysis uses the bundled FFmpeg decoder."))

    def set_project(self, project):
        self.player.stop()
        self.player.setSource(QUrl())
        self.project = project
        self.clip_id = None
        self._pending = None
        self._preview_end = None

    def _clip(self):
        return next((c for c in self.project.clips if c.id == self.clip_id), None) if self.project else None

    def seek_project(self, seconds: float, *, play: bool = False):
        clip, source = self.project.timeline().project_to_source(seconds)
        self._preview_end = None
        self._load(clip.id, source, play)

    def seek_source(self, seconds: float):
        if self._clip() is None:
            return
        seconds = self.project.timeline().source_to_project(self.clip_id, seconds)
        self.seek_project(seconds)

    def select_clip(self, clip_id: str, *, play: bool = False):
        clip = next(c for c in self.project.clips if c.id == clip_id)
        clip.end(self.project.get(clip.media_id).duration)
        self._preview_end = None
        self._load(clip_id, clip.source_in, play)

    def preview(self, clip_id: str, start: float, end: float):
        clip = next(c for c in self.project.clips if c.id == clip_id)
        duration = self.project.get(clip.media_id).duration
        if duration is None or not 0 <= start < end <= duration:
            raise ValueError("Select an interval inside the original source")
        self._preview_end = end
        self._load(clip_id, start, True)

    def _load(self, clip_id, seconds, play):
        previous_clip = self.clip_id
        self.clip_id = clip_id
        clip = self._clip()
        source = QUrl.fromLocalFile(self.project.get(clip.media_id).source)
        self._resume = play
        if source != self.player.source():
            self._pending = seconds
            self.player.stop()
            self.player.setSource(source)
            self.clipChanged.emit(clip_id)
        elif self._pending is not None:
            # A second seek while the same source loads must survive LoadedMedia.
            self._pending = seconds
            if previous_clip != clip_id:
                self.clipChanged.emit(clip_id)
        else:
            self._pending = None
            self.player.setPosition(round(seconds * 1000))
            if previous_clip != clip_id:
                self.clipChanged.emit(clip_id)
            self.player.play() if play else self.player.pause()

    def _media_status(self, status):
        if status in (QMediaPlayer.MediaStatus.LoadedMedia, QMediaPlayer.MediaStatus.BufferedMedia):
            if self._pending is not None:
                seconds, self._pending = self._pending, None
                self.player.setPosition(round(seconds * 1000))
                self.player.play() if self._resume else self.player.pause()
        elif status == QMediaPlayer.MediaStatus.EndOfMedia and self._pending is None:
            if self._preview_end is not None:
                self._preview_end = None
                self.player.pause()
            elif self._resume and self._clip() is not None and self.player.position() / 1000. >= self._clip().end(self.project.get(self._clip().media_id).duration) - .05:
                self._advance()

    def _advance(self):
        clips = self.project.clips
        index = next(i for i, c in enumerate(clips) if c.id == self.clip_id)
        if index + 1 < len(clips):
            self.select_clip(clips[index + 1].id, play=True)
        else:
            self._resume = False
            self.player.pause()

    def _position(self, milliseconds):
        if self._pending is not None or self._clip() is None:
            return
        source = milliseconds / 1000.
        clip = self._clip()
        if self._preview_end is not None and source >= self._preview_end:
            self._preview_end = None
            self._resume = False
            self.player.pause()
        elif self._preview_end is None and self._resume and source >= clip.end(self.project.get(clip.media_id).duration):
            self._advance()
            return
        try:
            project_seconds = self.project.timeline().source_to_project(clip.id, source)
            self.previewOutsideClip.emit(False)
        except ValueError:
            project_seconds = self.project.timeline().starts[clip.id]
            self.previewOutsideClip.emit(True)
        self.positionChanged.emit(project_seconds, source)

    def toggle(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._resume = False
            self.player.pause()
        else:
            if self.clip_id is None:
                if not self.project or not self.project.clips:
                    raise ValueError("Import media before playback")
                self.select_clip(self.project.clips[0].id, play=True)
            else:
                clip = self._clip()
                if self.player.position() / 1000. >= clip.end(self.project.get(clip.media_id).duration):
                    self.select_clip(clip.id, play=True)
                else:
                    self._resume = True
                    self.player.play()

    def pause(self):
        self._resume = False
        self.player.pause()
