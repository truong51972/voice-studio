"""Pack a signed-off PyInstaller onedir build in a stable-order release ZIP.

This script packages an *existing* platform-native distribution. It cannot
cross-compile Windows binaries from Linux/WSL.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(2 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

def pack(distribution: Path, output: Path) -> tuple[Path, Path]:
    if not distribution.is_dir():
        raise FileNotFoundError(distribution)
    if not any(distribution.iterdir()):
        raise ValueError("Refusing to archive an empty build")
    output.parent.mkdir(parents=True, exist_ok=True)
    files = sorted(p for p in distribution.rglob("*") if p.is_file() and not set(p.relative_to(distribution).parts).intersection({".models", ".settings", ".projects"}))
    # Normalize ZIP entry names/timestamps. Binary reproducibility still
    # depends on the PyInstaller build and frozen native dependencies.
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for file in files:
            relative = file.relative_to(distribution.parent)
            record = zipfile.ZipInfo(relative.as_posix(), date_time=(1980, 1, 1, 0, 0, 0))
            record.compress_type = zipfile.ZIP_DEFLATED
            record.external_attr = 0o644 << 16
            archive.writestr(record, file.read_bytes(), compress_type=zipfile.ZIP_DEFLATED)
    checksum_file = output.with_suffix(output.suffix + ".sha256")
    checksum_file.write_text(f"{sha256(output)}  {output.name}\n", encoding="utf-8")
    return output, checksum_file

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--platform", choices=["windows", "linux"], required=True)
    parser.add_argument("--dist", type=Path, default=ROOT / "dist" / "voice-studio")
    args = parser.parse_args()
    expected = "voice-studio.exe" if args.platform == "windows" else "voice-studio"
    if not (args.dist / expected).is_file():
        parser.error(f"Expected native executable not found: {args.dist / expected}")
    version = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    output = ROOT / "dist" / f"VoiceStudio-{version}-{args.platform}-x64.zip"
    archive, checksum = pack(args.dist, output)
    print(f"Release artifact: {archive}\nSHA-256: {checksum}")

if __name__ == "__main__":
    main()
