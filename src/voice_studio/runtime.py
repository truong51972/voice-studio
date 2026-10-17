from __future__ import annotations

import ctypes
import importlib.util
import os
import sys
from pathlib import Path

# Keep DLL-directory handles and explicitly loaded DLL handles alive for the
# whole process. On Windows, closing an AddDllDirectory handle removes it from
# the process DLL search path.
_DLL_DIR_HANDLES: list[object] = []
_PRELOADED_DLLS: list[object] = []
_CONFIGURED = False
_SELECTED_ORT_DLL: Path | None = None


def _unique_existing_dirs(paths: list[Path]) -> list[Path]:
    result: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        try:
            resolved = path.resolve()
        except OSError:
            continue
        key = os.path.normcase(str(resolved))
        if resolved.is_dir() and key not in seen:
            seen.add(key)
            result.append(resolved)
    return result


def _sherpa_package_dir() -> Path | None:
    """Locate sherpa_onnx without importing its native extension."""
    try:
        spec = importlib.util.find_spec("sherpa_onnx")
    except Exception:
        return None
    if spec is None:
        return None
    if spec.submodule_search_locations:
        try:
            return Path(next(iter(spec.submodule_search_locations))).resolve()
        except (StopIteration, OSError):
            pass
    if spec.origin:
        try:
            return Path(spec.origin).resolve().parent
        except OSError:
            return None
    return None


def _candidate_runtime_dirs() -> list[Path]:
    dirs: list[Path] = []
    pkg_dir = _sherpa_package_dir()
    if pkg_dir is not None:
        dirs.extend([pkg_dir / "lib", pkg_dir])

    # PyInstaller one-dir: bundled files live under sys._MEIPASS (usually
    # dist/<app>/_internal). Keep explicit paths for robustness across versions.
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        base = Path(sys._MEIPASS)
        dirs.extend(
            [
                base / "sherpa_onnx" / "lib",
                base / "sherpa_onnx",
                base,
            ]
        )
        exe_dir = Path(sys.executable).resolve().parent
        dirs.extend(
            [
                exe_dir / "_internal" / "sherpa_onnx" / "lib",
                exe_dir / "_internal" / "sherpa_onnx",
                exe_dir / "_internal",
                exe_dir,
            ]
        )
    else:
        # sherpa-onnx-core installs Windows native DLLs into the virtualenv
        # Scripts directory on current releases.
        dirs.extend(
            [
                Path(sys.prefix) / "Scripts",
                Path(sys.executable).resolve().parent,
            ]
        )

    return _unique_existing_dirs(dirs)


def _find_bundled_onnxruntime() -> Path | None:
    # Prefer sherpa's private runtime. Do not recursively inspect Windows/System32;
    # the purpose of this function is specifically to avoid accidentally loading a
    # stale system-wide onnxruntime.dll.
    for directory in _candidate_runtime_dirs():
        candidate = directory / "onnxruntime.dll"
        if candidate.is_file():
            return candidate.resolve()
    return None


def configure_windows_native_runtime(*, strict: bool = False) -> Path | None:
    """Prefer the ONNX Runtime bundled with sherpa-onnx on Windows.

    Some Windows machines contain an old ``onnxruntime.dll`` in System32. The
    Windows loader can resolve that DLL before sherpa's matching runtime, which
    produces errors such as "requested API version 27 ... only 1,17 supported".
    We prepend sherpa's runtime directories and preload its DLL by absolute path
    before importing ``sherpa_onnx``.
    """
    global _CONFIGURED, _SELECTED_ORT_DLL

    if sys.platform != "win32":
        return None
    if _CONFIGURED:
        return _SELECTED_ORT_DLL

    runtime_dirs = _candidate_runtime_dirs()
    ort_dll = _find_bundled_onnxruntime()

    if ort_dll is None:
        if strict:
            searched = "\n  - ".join(str(p) for p in runtime_dirs) or "(không có thư mục hợp lệ)"
            raise RuntimeError(
                "Không tìm thấy onnxruntime.dll đi kèm sherpa-onnx. "
                "Hãy chạy `uv sync --dev` và build lại. Đã tìm tại:\n  - " + searched
            )
        return None

    # Add package/runtime directories to Python's secure DLL search path and PATH.
    # Keep handles alive globally; otherwise the directories are removed again.
    for directory in runtime_dirs:
        try:
            handle = os.add_dll_directory(str(directory))
            _DLL_DIR_HANDLES.append(handle)
        except (AttributeError, FileNotFoundError, OSError):
            pass

    current_path = os.environ.get("PATH", "")
    prepend = [str(p) for p in runtime_dirs]
    os.environ["PATH"] = os.pathsep.join(prepend + ([current_path] if current_path else []))

    # Strongest guard: load the exact bundled runtime by absolute path *before*
    # sherpa's extension is imported. Windows will then reuse this loaded module
    # when resolving the extension's onnxruntime.dll dependency.
    try:
        loaded = ctypes.WinDLL(str(ort_dll))
        _PRELOADED_DLLS.append(loaded)
    except OSError as exc:
        raise RuntimeError(
            f"Không thể nạp ONNX Runtime đi kèm ứng dụng: {ort_dll}. "
            "Có thể bundle bị thiếu DLL phụ thuộc hoặc bị antivirus chặn."
        ) from exc

    _SELECTED_ORT_DLL = ort_dll
    _CONFIGURED = True
    return ort_dll


def selected_onnxruntime_path() -> str:
    return str(_SELECTED_ORT_DLL) if _SELECTED_ORT_DLL is not None else ""
