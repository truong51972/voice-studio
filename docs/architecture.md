# Voice Studio architecture (issue #3)

## Stable media-first UI

```text
MainWindow (one QMediaPlayer + QAudioOutput)
├─ shared PreviewVideoWidget (DetectionOverlay)
├─ LocatorPanelsMixin
│  ├─ Speakers → ReferenceInput
│  ├─ Analysis → SimilarityPlotWidget
│  └─ Segments → segment table
└─ shared EditorTimelineWidget
       ↕ seekRequested → MainWindow._seek_to_seconds → QMediaPlayer
```

The main window **owns the player and clock**, connects `QMediaPlayer.positionChanged` to the overlay/timeline/transport, and uses milliseconds only at the Qt boundary. Player selection, Locator profile and threshold semantics remain the same as in v0.5.1.

No extra player is created for future STT or diarization. New tasks will add inspector panels/tracks that subscribe to this same clock, not duplicate player state.

The `voice_studio.ui` package continues exporting `build_app`, `create_application`, `MainWindow`, `_parse_timecode` and existing classes for compatibility; the previous 1,000+ line `ui.py` was split without redesigning the layout.

## File responsibilities

- `ui/main_window.py`: app construction, common media playback, source selection, single seek/position state and rendering of Locator results.
- `ui/widgets/media_player.py`: preview and speaker overlay.
- `ui/widgets/timeline.py`: playhead and source-local timeline drawing.
- `ui/widgets/similarity_plot.py`: Qt similarity chart.
- `ui/panels/locator.py`: known-speaker inspector controls and segment table.
- `ui/panels/reference.py`: file/microphone reference enrollment.
- `ui/theme.py`, `ui/timecode.py`, `ui/resources.py`: palette, timestamp helpers and packaged resources.
- `ui/workers.py`: legacy QThread adapter, to be superseded by cancellable process workers in [#5](https://github.com/truong51972/voice-studio/issues/5).
- `service.py`: UI-independent `LocatorService.analyze()`, which delegates to the established `analyze_bundle` and leaves the Locator pipeline untouched.
- `domain/contracts.py`: frozen source-aligned media and result contracts with no Qt or Gradio dependency.

## Domain contract

`MediaAsset` describes **one source file**; `Segment`, `TranscriptSegment`, and `SpeakerTurn` use finite floating-point **seconds since that file's beginning**. Independent recordings have independent time origins; no concatenated offsets are introduced into persisted timestamps.

`ModelMetadata` / `RunMetadata` record immutable engine configuration and run provenance. `AnalysisResult` holds the **raw inference snapshot**. `TranscriptCorrection` represents editable user overrides separately; never write generated summary/guesses back into the raw transcript. Confidence is optional; unavailable confidence is `None`, not an invented probability. Speaker turns may remain anonymous/uncertain, distinct from verified identity.

For now these contracts are **prepared but not wired to the legacy Locator output**. Locator still produces `AnalysisBundle` and `MatchSegment`; adapters to common `AnalysisResult` and inference jobs will be added alongside #4–#6, with tests before any change to matching behavior.

## Legacy/deprecation boundaries

`prepare_audio` / `AudioInput` replace Gradio-era naming inside the Locator pipeline. The `prepare_gradio_audio` and `GradioAudio` aliases remain for callers/tests, pending deprecation after migration. Legacy Plotly-based reporting is not used by the PySide6 editor but remains temporarily for compatibility with existing pipeline helpers/tests. Drop the dependency only after dedicated tests have replaced those reports.

## Regression expectations

Run `uv sync --dev && uv run poe test` (`QT_QPA_PLATFORM=offscreen` on CI). Tests cover UI structure, splitter orientation, reference controls, selected models, seek and position propagation, icon lookup, source-local timecode, immutable contracts, source bounds, and independent Locator service delegation. Hardware tests for actual playback, microphone and GPU inference still require manual QA.
