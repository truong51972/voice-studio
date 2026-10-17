"""Optional developer CLI using the same model service as Settings → Models."""
from .model_catalog import descriptors
from .model_service import ModelService


def main():
    service = ModelService()
    for model in descriptors("locator"):
        def progress(stage, done, total, speed):
            print(f"{stage}: {done / 2**20:.1f}/{total / 2**20:.1f} MiB ({speed / 2**20:.1f} MiB/s)", flush=True)
        service.install(model, progress=progress)
        print(f"Installed {model.label}: {service.path(model)}")
