from __future__ import annotations

import os
import sys
import multiprocessing as mp

# Keep the local/offline application free from external telemetry.
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
os.environ['PYANNOTE_METRICS_ENABLED'] = '0'


def main() -> None:
    """Run the native desktop application.

    This function is the canonical application entrypoint used by both the
    installed ``voice-studio`` console script and ``python -m voice_studio``.
    """
    mp.freeze_support()
    if "--diagnostics" in sys.argv:
        from voice_studio.diagnostics import main as diagnostics_main
        diagnostics_main()
        return
    smoke_test = "--smoke-test" in sys.argv
    if smoke_test:
        # CI/build hosts may not expose a desktop display. Qt can still construct
        # the complete widget tree through its offscreen platform plugin.
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    # Configure Windows native DLL resolution before anything can import sherpa's
    # extension module. This protects the packaged app from stale System32 ORT DLLs.
    from voice_studio.runtime import (
        configure_windows_native_runtime,
        selected_onnxruntime_path,
    )

    configure_windows_native_runtime(strict=(sys.platform == "win32"))

    from voice_studio.ui import build_app, create_application

    qt_app = create_application(sys.argv)
    window = build_app()

    if smoke_test:
        import imageio_ffmpeg  # noqa: F401
        import PySide6  # noqa: F401
        if '--require-diarization' in sys.argv:
            # A requested runtime must import in the frozen app, not just the builder.
            import torch  # noqa: F401
            import torchaudio  # noqa: F401
            from pyannote.audio import Pipeline  # noqa: F401
            print('[smoke] Auto Detect pyannote/Torch runtime imports: OK (model installed separately)')
        # Optional STT runtime sanity test, without model downloads/inference.
        try:
            import faster_whisper  # noqa: F401
            import ctranslate2  # noqa: F401
            print("[smoke] Optional STT CPU runtime imports: OK")
        except ImportError:
            print("[smoke] Optional STT runtime not bundled (Locator-only build)")

        from voice_studio.embedding import SpeakerEmbedder
        from voice_studio.media import ffmpeg_executable
        from voice_studio.profiles import INFERENCE_PROFILES

        ort_path = selected_onnxruntime_path()
        if ort_path:
            print(f"[smoke] Bundled ONNX Runtime: {ort_path}")

        for profile in INFERENCE_PROFILES.values():
            embedder = SpeakerEmbedder(profile.model_path, num_threads=1)
            print(f"[smoke] {profile.label}: extractor initialized, dim={embedder.dim}")

        ffmpeg_path = ffmpeg_executable()
        print(f"[smoke] Bundled FFmpeg: {ffmpeg_path}")
        print("[smoke] PySide6 desktop UI + FFmpeg + all speaker profiles: OK")
        window.close()
        qt_app.quit()
        return

    window.show()
    raise SystemExit(qt_app.exec())


if __name__ == "__main__":
    main()
