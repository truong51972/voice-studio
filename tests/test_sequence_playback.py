from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtMultimedia import QMediaPlayer

from voice_studio.domain.timeline import TimelineClip
from voice_studio.projects import ProjectStore
from voice_studio.ui import create_application
from voice_studio.ui.playback import SequencePlayback


class Player(QObject):
    positionChanged = Signal(int)
    mediaStatusChanged = Signal(object)
    errorOccurred = Signal(object, str)

    def __init__(self):
        super().__init__()
        self.url = QUrl()
        self.ms = 0
        self.state = QMediaPlayer.PlaybackState.StoppedState
    def source(self):
        return self.url
    def setSource(self, url):
        self.url = url
    def position(self):
        return self.ms
    def setPosition(self, ms):
        self.ms = ms
        self.positionChanged.emit(ms)
    def play(self):
        self.state = QMediaPlayer.PlaybackState.PlayingState
    def pause(self):
        self.state = QMediaPlayer.PlaybackState.PausedState
    def stop(self):
        self.state = QMediaPlayer.PlaybackState.StoppedState
    def playbackState(self):
        return self.state
    def loaded(self):
        self.mediaStatusChanged.emit(QMediaPlayer.MediaStatus.LoadedMedia)


def sequence(tmp_path):
    create_application([])
    project = ProjectStore(tmp_path / 'project')
    paths = []
    for index in range(3):
        path = tmp_path / f'{index}.wav'
        path.write_bytes(b'audio')
        paths.append(path)
    project.add(paths)
    for media in project.items:
        media.duration = 20.
    project.trim_clip(project.clips[0].id, 2., 7.)
    project.trim_clip(project.clips[1].id, 4., 10.)
    project.trim_clip(project.clips[2].id, 1., 6.)
    player = Player()
    playback = SequencePlayback(player)
    playback.set_project(project)
    return project, player, playback


def test_seek_and_sequential_play_use_source_offsets_at_all_boundaries(tmp_path):
    project, player, playback = sequence(tmp_path)
    playback.seek_project(5., play=True)
    player.loaded()
    assert playback.clip_id == project.clips[1].id
    assert player.position() == 4000
    player.setPosition(10000)
    assert playback.clip_id == project.clips[2].id
    player.loaded()
    assert player.position() == 1000
    assert player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
    player.setPosition(6000)
    assert player.playbackState() == QMediaPlayer.PlaybackState.PausedState
    playback.seek_project(0.)
    player.loaded()
    assert player.position() == 2000


def test_preview_stops_at_selection_and_does_not_advance_project(tmp_path):
    project, player, playback = sequence(tmp_path)
    playback.preview(project.clips[0].id, 10., 12.)  # outside trim but inside original source
    player.loaded()
    assert player.position() == 10000
    player.setPosition(12000)
    assert player.playbackState() == QMediaPlayer.PlaybackState.PausedState
    assert playback.clip_id == project.clips[0].id


def test_repeated_source_clips_do_not_skip_on_stale_end_event(tmp_path):
    project, player, playback = sequence(tmp_path)
    first = project.clips[0]
    project.clips = [TimelineClip(first.id, first.media_id, 18., 20.),
                     TimelineClip('repeat', first.media_id, 2., 5.)]
    playback.select_clip(first.id, play=True)
    player.loaded()
    player.setPosition(20000)
    assert playback.clip_id == 'repeat'
    assert player.position() == 2000
    player.mediaStatusChanged.emit(QMediaPlayer.MediaStatus.EndOfMedia)
    assert player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
    assert playback.clip_id == 'repeat'


def test_reference_seek_during_initial_load_is_applied_when_media_is_ready(tmp_path):
    project, player, playback = sequence(tmp_path)
    clip = project.clips[0]
    playback.select_clip(clip.id)
    playback.preview(clip.id, 3., 4.)
    assert player.playbackState() != QMediaPlayer.PlaybackState.PlayingState
    player.loaded()
    assert player.position() == 3000
    assert player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
    player.setPosition(4000)
    assert player.playbackState() == QMediaPlayer.PlaybackState.PausedState
