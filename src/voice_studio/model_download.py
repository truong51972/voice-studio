"""Application-owned speaker model downloader, also used by the developer CLI."""
from __future__ import annotations

import hashlib
import os
import socket
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import MODEL_DIR
from .profiles import INFERENCE_PROFILES, InferenceProfile

CHUNK_SIZE = 1024 * 1024
NETWORK_TIMEOUT_SECONDS = 30
RETRIES_PER_URL = 2


def _mib(value: int) -> float:
    return value / (1024 * 1024)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def validate_model(path: Path, profile: InferenceProfile, *, verbose: bool = True) -> bool:
    if not path.is_file():
        return False

    size = path.stat().st_size
    if size != profile.model_size:
        if verbose:
            print(
                f"[invalid] {path.name}: size {size:,} bytes; expected {profile.model_size:,} bytes",
                flush=True,
            )
        return False

    actual_hash = _sha256(path)
    if actual_hash.lower() != profile.model_sha256.lower():
        if verbose:
            print(
                f"[invalid] {path.name}: SHA-256 mismatch\n"
                f"          actual:   {actual_hash}\n"
                f"          expected: {profile.model_sha256}",
                flush=True,
            )
        return False

    return True


def _progress(downloaded: int, expected_size: int, started_at: float, *, final: bool = False) -> None:
    elapsed = max(time.monotonic() - started_at, 0.001)
    speed = downloaded / elapsed
    pct = min(downloaded / expected_size * 100.0, 100.0)
    suffix = "\n" if final else "\r"
    print(
        f"[progress] {pct:6.2f}%  "
        f"{_mib(downloaded):5.1f}/{_mib(expected_size):.1f} MiB  "
        f"{_mib(int(speed)):.1f} MiB/s",
        end=suffix,
        flush=True,
    )


def _download_once(url: str, part_path: Path, expected_size: int) -> None:
    resume_from = part_path.stat().st_size if part_path.exists() else 0
    if resume_from >= expected_size:
        part_path.unlink(missing_ok=True)
        resume_from = 0

    headers = {
        "User-Agent": "AI-Voice-Locator/0.5",
        "Accept": "application/octet-stream",
    }
    if resume_from:
        headers["Range"] = f"bytes={resume_from}-"
        print(f"[resume] continuing from {_mib(resume_from):.1f} MiB", flush=True)

    request = Request(url, headers=headers)
    started_at = time.monotonic()
    last_report = started_at

    with urlopen(request, timeout=NETWORK_TIMEOUT_SECONDS) as response:
        status = getattr(response, "status", response.getcode())
        append = bool(resume_from and status == 206)
        if resume_from and not append:
            print("[resume] server ignored Range; restarting this download", flush=True)
            resume_from = 0

        mode = "ab" if append else "wb"
        downloaded = resume_from
        with part_path.open(mode) as output:
            while True:
                chunk = response.read(CHUNK_SIZE)
                if not chunk:
                    break
                output.write(chunk)
                downloaded += len(chunk)

                now = time.monotonic()
                if now - last_report >= 0.75 or downloaded >= expected_size:
                    _progress(downloaded, expected_size, started_at)
                    last_report = now

        _progress(downloaded, expected_size, started_at, final=True)

    actual_size = part_path.stat().st_size
    if actual_size != expected_size:
        raise RuntimeError(
            f"download incomplete: got {actual_size:,} bytes, expected {expected_size:,} bytes"
        )


def _download_model(profile: InferenceProfile, destination: Path) -> None:
    part_path = destination.with_suffix(destination.suffix + ".part")
    failures: list[str] = []

    print(
        f"[download] {profile.label}: {profile.model_filename} ({_mib(profile.model_size):.1f} MiB)",
        flush=True,
    )
    print(
        f"[info] network timeout: {NETWORK_TIMEOUT_SECONDS}s without data; automatic retries/fallback enabled",
        flush=True,
    )

    for source_index, url in enumerate(profile.download_urls, start=1):
        host = url.split("/", 3)[2]
        print(f"[source {source_index}/{len(profile.download_urls)}] {host}", flush=True)
        for attempt in range(1, RETRIES_PER_URL + 1):
            try:
                if attempt > 1:
                    print(f"[retry] attempt {attempt}/{RETRIES_PER_URL}", flush=True)
                _download_once(url, part_path, profile.model_size)
                print("[verify] checking SHA-256...", flush=True)
                if not validate_model(part_path, profile):
                    raise RuntimeError("downloaded file failed integrity verification")
                os.replace(part_path, destination)
                print(f"[ok] {destination} ({_mib(destination.stat().st_size):.1f} MiB)", flush=True)
                return
            except (HTTPError, URLError, TimeoutError, socket.timeout, OSError, RuntimeError) as exc:
                message = f"{host} attempt {attempt}: {type(exc).__name__}: {exc}"
                failures.append(message)
                print(f"[warning] {message}", flush=True)

        print("[fallback] switching download source...", flush=True)

    detail = "\n  - ".join(failures)
    raise RuntimeError(
        f"Unable to download {profile.label} model from all configured sources.\n"
        f"  - {detail}\n\n"
        "You can also download the model manually and place it at:\n"
        f"  {destination}\n"
        f"Expected size: {profile.model_size:,} bytes\n"
        f"Expected SHA-256: {profile.model_sha256}\n"
        "Then run `uv run poe models` again."
    )


def ensure_model(profile: InferenceProfile, destination: Path | None = None) -> None:
    destination = destination if destination is not None else MODEL_DIR / profile.model_filename
    destination.parent.mkdir(parents=True, exist_ok=True)

    if validate_model(destination, profile, verbose=False):
        print(
            f"[skip] {profile.label}: {profile.model_filename} is already valid "
            f"({_mib(destination.stat().st_size):.1f} MiB, SHA-256 OK)",
            flush=True,
        )
        return

    if destination.exists():
        size = destination.stat().st_size
        part_path = destination.with_suffix(destination.suffix + ".part")
        if 0 < size < profile.model_size and not part_path.exists():
            print(
                f"[repair] preserving interrupted download ({_mib(size):.1f}/{_mib(profile.model_size):.1f} MiB)",
                flush=True,
            )
            os.replace(destination, part_path)
        else:
            print("[repair] existing model is incomplete/corrupt; downloading again", flush=True)
            destination.unlink()

    _download_model(profile, destination)


def main() -> None:
    for profile in INFERENCE_PROFILES.values():
        ensure_model(profile)


if __name__ == "__main__":
    main()
