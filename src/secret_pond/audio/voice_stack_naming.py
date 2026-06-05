from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from secret_pond.paths import ProjectPaths

_KST = ZoneInfo("Asia/Seoul")


def voice_recording_filename(timestamp: datetime) -> str:
    return _timestamped_filename("VR", timestamp)


def voice_stack_filename(timestamp: datetime) -> str:
    return _timestamped_filename("VS", timestamp)


def next_voice_raw_path(paths: ProjectPaths, *, now: datetime | None = None) -> Path:
    paths.voice_raw_sources_dir.mkdir(parents=True, exist_ok=True)
    return _next_timestamped_path(
        paths.voice_raw_sources_dir,
        voice_recording_filename(now or datetime.now(UTC)),
    )


def next_voice_stack_path(paths: ProjectPaths, *, now: datetime | None = None) -> Path:
    paths.voice_stack_sources_dir.mkdir(parents=True, exist_ok=True)
    return _next_timestamped_path(
        paths.voice_stack_sources_dir,
        voice_stack_filename(now or datetime.now(UTC)),
    )


def _timestamped_filename(prefix: str, timestamp: datetime) -> str:
    kst_timestamp = timestamp.astimezone(_KST)
    return f"{prefix}{kst_timestamp:%m%d_%H%M%S}.wav"


def _next_timestamped_path(directory: Path, filename: str) -> Path:
    candidate = directory / filename
    if not candidate.exists():
        return candidate

    stem = candidate.stem
    suffix = 2
    while True:
        suffixed = directory / f"{stem}_{suffix}{candidate.suffix}"
        if not suffixed.exists():
            return suffixed
        suffix += 1
