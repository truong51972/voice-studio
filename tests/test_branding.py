from pathlib import Path


def test_new_package_identity():
    root = Path(__file__).resolve().parents[1]
    project = (root / "pyproject.toml").read_text(encoding="utf-8")
    assert 'name = "voice-studio"' in project
    assert 'voice-studio = "voice_studio.app:main"' in project
    assert (root / "src" / "voice_studio" / "__main__.py").is_file()
    assert not (root / "src" / "voice_locator").exists()


def test_product_does_not_advertise_incomplete_features():
    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
    assert "not implemented yet" in readme
