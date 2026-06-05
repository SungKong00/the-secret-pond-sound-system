from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from secret_pond.audio.source_library import selected_source_path
from secret_pond.config import AppSettings
from secret_pond.paths import ProjectPaths


class EventLogReader(Protocol):
    def read_events(self, limit: int | None = None) -> list[dict[str, Any]]: ...


def diagnostics_payload(
    paths: ProjectPaths,
    settings: AppSettings,
    logger: EventLogReader,
) -> dict[str, Any]:
    low_source = selected_source_path(paths, settings, "low") or paths.low_source
    mid_source = selected_source_path(paths, settings, "mid") or paths.mid_source
    voice_source = selected_source_path(paths, settings, "voice_stack") or paths.voice_stack_raw
    return {
        "sources": [
            file_status_payload(paths.root, "low", "Low Source", low_source),
            file_status_payload(paths.root, "mid", "Mid Source", mid_source),
            file_status_payload(paths.root, "voice", "Voice Stack", voice_source),
        ],
        "events": event_log_payload(paths, logger),
    }


def file_status_payload(root: Path, file_id: str, label: str, path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "id": file_id,
            "label": label,
            "path": relative_path(root, path),
            "exists": False,
            "size_bytes": 0,
            "modified_at": None,
        }

    stat = path.stat()
    return {
        "id": file_id,
        "label": label,
        "path": relative_path(root, path),
        "exists": True,
        "size_bytes": stat.st_size,
        "modified_at": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(),
    }


def event_log_payload(
    paths: ProjectPaths,
    logger: EventLogReader,
    limit: int = 5,
) -> dict[str, Any]:
    path = paths.event_log_file
    try:
        events = logger.read_events()
    except (OSError, ValueError) as exc:
        return {
            "path": relative_path(paths.root, path),
            "exists": path.exists(),
            "recent": [],
            "error": str(exc),
        }

    return {
        "path": relative_path(paths.root, path),
        "exists": path.exists(),
        "recent": list(reversed(events[-limit:])),
        "error": None,
    }


def relative_path(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()
