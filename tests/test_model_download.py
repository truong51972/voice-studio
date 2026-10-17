from voice_studio import model_download
from voice_studio.model_catalog import descriptors


def test_developer_cli_uses_same_portable_service_for_all_speaker_profiles(monkeypatch, tmp_path):
    installed = []
    class Service:
        def install(self, model, **kwargs):
            installed.append(model.id)
            kwargs['progress']('Downloading', 1, 1, 1)
        def path(self, model):
            return tmp_path / model.id
    monkeypatch.setattr(model_download, 'ModelService', Service)
    model_download.main()
    assert installed == [m.id for m in descriptors('locator')]
