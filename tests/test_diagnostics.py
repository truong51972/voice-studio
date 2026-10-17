from voice_studio import diagnostics


def test_runtime_probe_reports_native_load_errors_and_continues(monkeypatch):
    imported = []

    def probe(name):
        imported.append(name)
        if name == "ctranslate2":
            raise OSError("missing native library")

    monkeypatch.setattr(diagnostics.importlib, "import_module", probe)
    assert diagnostics.runtime_import_errors() == {"ctranslate2": "OSError: missing native library"}
    assert imported == list(diagnostics.CORE_RUNTIMES)


def test_default_diagnostics_do_not_import_inference_backends(monkeypatch):
    def unexpected_import(_name):
        raise AssertionError("Presence diagnostics must not import inference backends")

    monkeypatch.setattr(diagnostics.importlib, "import_module", unexpected_import)
    checks = diagnostics.diagnose()
    assert "pyannote.audio" in checks["runtime"]
    assert "pyannote-community-1" in checks["models"]
