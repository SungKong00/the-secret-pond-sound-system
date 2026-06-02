from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from secret_pond.paths import ProjectPaths


class ParticipantCounter:
    def __init__(self, paths: ProjectPaths) -> None:
        self._paths = paths

    def get_count(self) -> int:
        if not self._paths.participant_count_file.exists():
            return 0
        return _read_count(self._paths.participant_count_file)

    def increment(self) -> int:
        count = self.get_count() + 1
        _write_count_atomic(self._paths.participant_count_file, count)
        return count

    def reset(self) -> int:
        if self._paths.participant_count_file.exists():
            _read_count(self._paths.participant_count_file)
        _write_count_atomic(self._paths.participant_count_file, 0)
        return 0


def _read_count(path: Path) -> int:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        msg = "participant count file is not valid JSON"
        raise ValueError(msg) from exc

    count = payload.get("count") if isinstance(payload, dict) else None
    if type(count) is not int or count < 0:
        msg = "participant count file must contain a non-negative integer count"
        raise ValueError(msg)
    return count


def _write_count_atomic(path: Path, count: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.stem}.{uuid4().hex}.tmp")
    try:
        temp_path.write_text(
            json.dumps({"count": count}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temp_path.replace(path)
    finally:
        if temp_path.exists():
            temp_path.unlink()
