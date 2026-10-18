import faulthandler
import pytest

# Native Qt/FFmpeg shutdown failures can occur *after* pytest has printed
# "all passed"; keep the C-level traceback so a non-zero exit is diagnosable.
faulthandler.enable(all_threads=True)


@pytest.fixture(autouse=True)
def portable_test_home(tmp_path, monkeypatch):
    monkeypatch.setenv("VOICE_STUDIO_DATA_DIR", str(tmp_path / "app"))
    monkeypatch.delenv("VOICE_STUDIO_MODEL_DIR", raising=False)


@pytest.fixture(scope="session", autouse=True)
def keep_qt_application_alive():
    """Qt objects may outlive individual tests; own QApplication until suite ends.

    PySide6/QMultimedia teardown during Python interpreter finalization has
    caused intermittent native exit 139/abort after all tests passed. Holding
    one app for the whole suite lets the event queue drain and Python collect
    QObject owners *before* interpreter shutdown.
    """
    from voice_studio.ui import create_application
    import gc

    app = create_application([])
    yield
    # QtMultimedia owns native FFmpeg objects; destroy their QWidget parents
    # while the Python/Qt runtime is still live rather than at interpreter exit.
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication
    import shiboken6

    for widget in QApplication.topLevelWidgets():
        widget.close()
        widget.deleteLater()
    app.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    gc.collect()
    app.processEvents()
    app.quit()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    shiboken6.delete(app)
    gc.collect()
