from pathlib import Path


def test_new_package_identity():
    root = Path(__file__).resolve().parents[1]
    project = (root / "pyproject.toml").read_text(encoding="utf-8")
    assert 'name = "voice-studio"' in project
    assert 'voice-studio = "voice_studio.app:main"' in project
    assert (root / "src" / "voice_studio" / "__main__.py").is_file()
    assert not (root / "src" / "voice_locator").exists()


def test_product_distinguishes_merged_features_from_release_validation():
    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
    assert "Development preview" in readme
    assert "STT" in readme
    assert "Windows packaging" in readme
    assert "not yet been signed off" in readme
    assert "Implementation PRs #15–#23 have all been merged" in readme
