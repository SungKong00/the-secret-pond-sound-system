from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4


@dataclass(frozen=True)
class FileSnapshot:
    existed: bool
    data: bytes


def capture_file_snapshot(path: Path) -> FileSnapshot:
    if path.exists():
        return FileSnapshot(existed=True, data=path.read_bytes())
    return FileSnapshot(existed=False, data=b"")


def restore_file_snapshot(path: Path, snapshot: FileSnapshot) -> None:
    if not snapshot.existed:
        path.unlink(missing_ok=True)
        return

    temp_path = path.with_name(f".{path.stem}.{uuid4().hex}.rollback.tmp")
    try:
        temp_path.write_bytes(snapshot.data)
        temp_path.replace(path)
    finally:
        if temp_path.exists():
            temp_path.unlink()
