from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUILD_SCRIPT = ROOT / "scripts" / "build.py"


def _load_build_module():
    spec = importlib.util.spec_from_file_location("voice_studio_build", BUILD_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_windows_build_uses_valid_png_icon_source() -> None:
    build = _load_build_module()
    assert build.APP_ICON.name == "voice-studio.png"
    assert build.APP_ICON.read_bytes().startswith(build.PNG_SIGNATURE)
    build._verify_assets()
