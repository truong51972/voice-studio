from __future__ import annotations

import os
import sys
import multiprocessing as mp

# Keep the local/offline application free from external telemetry.
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
os.environ.setdefault("PYANNOTE_METRICS_ENABLED", "0")


def main() -> None:
    """Run the native desktop application.

    This function is the canonical application entrypoint used by both the
    installed ``voice-studio`` console script and ``python -m voice_studio``.
    """
    mp.freeze_support()
    if "--diagnostics" in sys.argv:
        from voice_studio.diagnostics import main as diagnostics_main
        sys.argv.remove("--diagnostics")
        diagnostics_main()
        return
    if "--model-probe" in sys.argv:
        from voice_studio.model_backends import main as probe_main
        sys.argv.remove("--model-probe")
        probe_main()
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
    if not smoke_test:
        from voice_studio.diagnostics import runtime_presence
        missing = [name for name, present in runtime_presence().items() if not present]
        if missing:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(
                None, "Incomplete application installation",
                "Required application runtimes are missing: " + ", ".join(missing)
                + ". Repair or reinstall Voice Studio before using these features.",
            )
    window = build_app()

    if smoke_test:
        from voice_studio.diagnostics import runtime_import_errors
        errors = runtime_import_errors()
        if errors:
            raise RuntimeError(f"Required production runtimes failed to import: {errors}")
        print("[smoke] All production runtime imports: OK (native GPU readiness not checked)")

        from voice_studio.embedding import SpeakerEmbedder
        from voice_studio.media import ffmpeg_executable
        from voice_studio.profiles import INFERENCE_PROFILES

        ort_path = selected_onnxruntime_path()
        if ort_path:
            print(f"[smoke] Bundled ONNX Runtime: {ort_path}")

        # Models are user data and are intentionally absent from a fresh bundle.
        from voice_studio.model_catalog import descriptors
        if len(descriptors()) < 3:
            raise RuntimeError("Packaged model catalog is incomplete")
        print("[smoke] Bundled catalogs available; no weights downloaded or required.")

        ffmpeg_path = ffmpeg_executable()
        print(f"[smoke] Bundled FFmpeg: {ffmpeg_path}")
        print("[smoke] PySide6 desktop UI + FFmpeg + production runtimes + catalogs: OK")
        window.close()
        qt_app.quit()
        return

    window.show()
    raise SystemExit(qt_app.exec())


if __name__ == "__main__":
    main()
