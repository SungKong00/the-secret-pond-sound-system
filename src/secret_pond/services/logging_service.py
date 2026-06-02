from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from secret_pond.paths import ProjectPaths


class EventLogger:
    def __init__(self, paths: ProjectPaths) -> None:
        self._paths = paths

    def log_event(
        self,
        event_type: str,
        payload: Mapping[str, Any] | None = None,
        *,
        timestamp: str | None = None,
    ) -> dict[str, Any]:
        event = {
            "timestamp": timestamp or datetime.now(UTC).isoformat(),
            "event_type": event_type,
            "payload": _json_safe_payload(payload),
        }
        encoded = json.dumps(event, ensure_ascii=False, sort_keys=True)

        self._paths.ensure_directories()
        with self._paths.event_log_file.open("a", encoding="utf-8") as file:
            file.write(f"{encoded}\n")
        return event

    def read_events(self, limit: int | None = None) -> list[dict[str, Any]]:
        if limit is not None and limit < 0:
            msg = "limit must be non-negative"
            raise ValueError(msg)
        if not self._paths.event_log_file.exists():
            return []

        events: list[dict[str, Any]] = []
        with self._paths.event_log_file.open(encoding="utf-8") as file:
            for line_number, line in enumerate(file, start=1):
                if limit is not None and len(events) >= limit:
                    break
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    event = json.loads(stripped)
                except json.JSONDecodeError as exc:
                    msg = f"event log contains invalid JSON on line {line_number}"
                    raise ValueError(msg) from exc
                if not isinstance(event, dict):
                    msg = f"event log line {line_number} must be a JSON object"
                    raise ValueError(msg)
                events.append(event)
        return events


def _json_safe_payload(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    if payload is None:
        return {}
    if not isinstance(payload, Mapping):
        msg = "payload must be a mapping"
        raise TypeError(msg)

    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    decoded = json.loads(encoded)
    if not isinstance(decoded, dict):
        msg = "payload must serialize to a JSON object"
        raise TypeError(msg)
    return decoded
