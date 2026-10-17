from __future__ import annotations

import argparse
import importlib.util
import os
import platform
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_NAME = "voice-studio"
ASSETS_DIR = ROOT / "assets"
APP_ICON = ASSETS_DIR / "voice-studio.png"
APP_ENTRYPOINT = ROOT / "src" / "voice_studio" / "app.py"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _package_dir(package: str) -> Path:
    spec = importlib.util.find_spec(package)
    if spec is None:
        raise SystemExit(
            f"Không tìm thấy package `{package}` trong môi trường hiện tại. "
            "Chạy `uv sync --dev` trước khi build."
        )
    if spec.submodule_search_locations:
        try:
            return Path(next(iter(spec.submodule_search_locations))).resolve()
        except StopIteration:
            pass
    if spec.origin is None:
        raise SystemExit(f"Không xác định được thư mục của package `{package}`.")
    return Path(spec.origin).resolve().parent


def _find_windows_onnxruntime_dll() -> Path:
    """Find the ONNX Runtime that belongs to the installed sherpa release."""
    sherpa_dir = _package_dir("sherpa_onnx")
    candidates = [
        sherpa_dir / "lib" / "onnxruntime.dll",
        sherpa_dir / "onnxruntime.dll",
        Path(sys.prefix) / "Scripts" / "onnxruntime.dll",
        Path(sys.executable).resolve().parent / "onnxruntime.dll",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    pretty = "\n  - ".join(str(path) for path in candidates)
    raise SystemExit(
        "Không tìm thấy onnxruntime.dll của sherpa-onnx-core trong môi trường Windows.\n"
        "Hãy chạy `uv sync --dev --refresh` trước khi build. Đã kiểm tra:\n  - " + pretty
    )


def _is_wsl() -> bool:
    release = platform.release().lower()
    return os.name != "nt" and ("microsoft" in release or "wsl" in release)


def _verify_models() -> None:
    from voice_studio.profiles import INFERENCE_PROFILES
    from voice_studio.model_registry import get_model, installed

    missing = [
        profile.model_path for key, profile in INFERENCE_PROFILES.items()
        if not installed(get_model("locator-" + key))
    ]
    if missing:
        pretty = "\n  - ".join(str(path) for path in missing)
        raise SystemExit("Thiếu model. Chạy `poe models` trước khi build.\n  - " + pretty)


def _verify_assets() -> None:
    if not APP_ICON.is_file():
        raise SystemExit(f"Thiếu application icon asset:\n  - {APP_ICON}")
    if APP_ICON.read_bytes()[: len(PNG_SIGNATURE)] != PNG_SIGNATURE:
        raise SystemExit(
            "Application icon source không phải PNG hợp lệ:\n"
            f"  - {APP_ICON}\n"
            "Windows build dùng PNG làm source-of-truth và để PyInstaller/Pillow chuyển sang ICO."
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--with-stt", action="store_true", help="Bundle optional offline faster-whisper runtime")
    parser.add_argument("--with-diarization", action="store_true", help="Bundle optional local pyannote/Torch runtime (no Community-1 model)")
    args = parser.parse_args()
    _protect_portable_projects(ROOT / "dist" / APP_NAME)
    _verify_models()
    _verify_assets()

    if not APP_ENTRYPOINT.is_file():
        raise SystemExit(f"Thiếu package entrypoint: {APP_ENTRYPOINT}")

    sep = ";" if os.name == "nt" else ":"
    cmd = [
        "pyinstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--name",
        APP_NAME,
        "--paths",
        str(ROOT / "src"),
        "--add-data",
        f"{ROOT / 'models'}{sep}models",
        "--add-data",
        f"{APP_ICON}{sep}assets",
        "--collect-all",
        "sherpa_onnx",
        "--collect-all",
        "imageio_ffmpeg",
        "--hidden-import",
        "PySide6.QtMultimedia",
        "--hidden-import",
        "PySide6.QtMultimediaWidgets",
    ]

    if args.with_stt:
        required = ("faster_whisper", "ctranslate2", "huggingface_hub")
        missing_backends = [name for name in required if importlib.util.find_spec(name) is None]
        if missing_backends:
            raise SystemExit(
                "Install optional STT runtime before building: uv sync --dev --extra stt; "
                + ", ".join(missing_backends)
            )
        for name in required:
            cmd += ["--collect-all", name]
        print("[build] Including offline STT runtime; no speech models are shipped.")

    if args.with_diarization:
        required = ('pyannote.audio', 'torch', 'torchaudio', 'huggingface_hub')
        missing = []
        for name in required:
            try:
                if importlib.util.find_spec(name) is None:
                    missing.append(name)
            except ModuleNotFoundError:
                missing.append(name)
        if missing:
            raise SystemExit('Install optional diarization runtime before building: uv sync --dev --extra diarization; ' + ', '.join(missing))
        for name in required:
            cmd += ['--collect-all', name]
        print('[build] Including optional Community-1 runtime; install the local model separately. Native QA is required.')

    bundled_ort_source: Path | None = None
    if os.name == "nt":
        bundled_ort_source = _find_windows_onnxruntime_dll()
        cmd += [
            "--add-binary",
            f"{bundled_ort_source}{sep}sherpa_onnx/lib",
            "--icon",
            str(APP_ICON),
        ]

    cmd.append(str(APP_ENTRYPOINT))

    system = platform.system()
    print(f"[build] Host platform: {system} ({platform.release()})")
    if bundled_ort_source is not None:
        print(f"[build] sherpa ONNX Runtime source: {bundled_ort_source}")
    if _is_wsl():
        print(
            "[build][warning] Bạn đang build trong WSL/Linux. "
            "PyInstaller sẽ tạo Linux executable, KHÔNG tạo file .exe.\n"
            "[build][warning] Muốn tạo Windows .exe, hãy chạy `uv run poe build` "
            "từ PowerShell/CMD bằng Python/uv của Windows."
        )

    print("[build]", " ".join(cmd))
    subprocess.run(cmd, cwd=ROOT, check=True)

    dist_dir = ROOT / "dist" / APP_NAME
    internal_dir = dist_dir / "_internal"
    executable = dist_dir / (f"{APP_NAME}.exe" if os.name == "nt" else APP_NAME)

    required_outputs = {
        "executable": executable,
        "assets/voice-studio.png": internal_dir / "assets" / "voice-studio.png",
    }
    if os.name == "nt":
        required_outputs["sherpa_onnx/lib/onnxruntime.dll"] = (
            internal_dir / "sherpa_onnx" / "lib" / "onnxruntime.dll"
        )

    missing = [f"{label}: {path}" for label, path in required_outputs.items() if not path.is_file()]
    if missing:
        raise SystemExit(
            "Build kết thúc nhưng thiếu artifact/runtime resource bắt buộc:\n  - "
            + "\n  - ".join(missing)
            + "\nKhông nên bàn giao thư mục dist này."
        )

    for label, path in required_outputs.items():
        print(f"[ok] {label}: {path}")

    print("[build] Running packaged executable smoke test...")
    try:
        smoke = subprocess.run(
            [str(executable), "--smoke-test"],
            cwd=dist_dir,
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired as exc:
        raise SystemExit(
            "Packaged executable smoke test bị timeout. "
            "Bundle có thể vẫn còn dependency/runtime issue."
        ) from exc

    if smoke.stdout:
        print(smoke.stdout.rstrip())
    if smoke.returncode != 0:
        if smoke.stderr:
            print(smoke.stderr.rstrip())
        raise SystemExit(
            f"Packaged executable smoke test FAILED (exit={smoke.returncode}). "
            "Không nên bàn giao thư mục dist này."
        )

    print("[ok] Packaged executable smoke test passed.")
    if os.name == "nt":
        print(f"[ok] Windows build hoàn tất: {executable}")
    else:
        print(f"[ok] Build hoàn tất cho {system}: {executable}")


def _protect_portable_projects(distribution: Path) -> None:
    if (distribution / ".projects").exists():
        raise SystemExit(
            f"Refusing to overwrite a portable installation containing {distribution / '.projects'}. "
            "Back up/move the entire .projects folder outside dist before rebuilding."
        )


if __name__ == "__main__":
    main()
