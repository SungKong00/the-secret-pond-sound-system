from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4


@dataclass(frozen=True)
class StackHistoryRecord:
    id: str
    kind: str
    created_at: str
    parent_version_id: str | None
    stack_path: str
    duration_seconds: float
    file_size: int
    sha256: str
    added_chunks: int
    peak_before_guard: float | None = None
    peak_after_guard: float | None = None
    gain_reduction_db: float | None = None


class StackHistoryStore:
    def __init__(self, path: Path) -> None:
        self._path = path

    def record_seed(
        self,
        *,
        stack_path: str,
        duration_seconds: float,
        file_size: int,
        sha256: str,
    ) -> StackHistoryRecord:
        return self._insert(
            kind="seed",
            parent_version_id=None,
            stack_path=stack_path,
            duration_seconds=duration_seconds,
            file_size=file_size,
            sha256=sha256,
            added_chunks=0,
            peak_before_guard=None,
            peak_after_guard=None,
            gain_reduction_db=None,
        )

    def record_commit(
        self,
        *,
        parent_version_id: str | None,
        stack_path: str,
        duration_seconds: float,
        file_size: int,
        sha256: str,
        added_chunks: int,
        peak_before_guard: float,
        peak_after_guard: float,
        gain_reduction_db: float,
    ) -> StackHistoryRecord:
        return self._insert(
            kind="commit",
            parent_version_id=parent_version_id,
            stack_path=stack_path,
            duration_seconds=duration_seconds,
            file_size=file_size,
            sha256=sha256,
            added_chunks=added_chunks,
            peak_before_guard=peak_before_guard,
            peak_after_guard=peak_after_guard,
            gain_reduction_db=gain_reduction_db,
        )

    def latest(self) -> StackHistoryRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "select * from stack_versions order by created_at desc, rowid desc limit 1",
            ).fetchone()
        return None if row is None else _record_from_row(row)

    def get(self, record_id: str) -> StackHistoryRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "select * from stack_versions where id = ?",
                (record_id,),
            ).fetchone()
        return None if row is None else _record_from_row(row)

    def list_versions(self) -> list[StackHistoryRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                "select * from stack_versions order by created_at desc, rowid desc",
            ).fetchall()
        return [_record_from_row(row) for row in rows]

    def _insert(
        self,
        *,
        kind: str,
        parent_version_id: str | None,
        stack_path: str,
        duration_seconds: float,
        file_size: int,
        sha256: str,
        added_chunks: int,
        peak_before_guard: float | None,
        peak_after_guard: float | None,
        gain_reduction_db: float | None,
    ) -> StackHistoryRecord:
        record = StackHistoryRecord(
            id=f"stack_{uuid4().hex}",
            kind=kind,
            created_at=datetime.now(UTC).isoformat(),
            parent_version_id=parent_version_id,
            stack_path=stack_path,
            duration_seconds=duration_seconds,
            file_size=file_size,
            sha256=sha256,
            added_chunks=added_chunks,
            peak_before_guard=peak_before_guard,
            peak_after_guard=peak_after_guard,
            gain_reduction_db=gain_reduction_db,
        )
        with self._connect() as connection:
            connection.execute(
                """
                insert into stack_versions (
                  id, kind, created_at, parent_version_id, stack_path,
                  duration_seconds, file_size, sha256, added_chunks,
                  peak_before_guard, peak_after_guard, gain_reduction_db
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    record.kind,
                    record.created_at,
                    record.parent_version_id,
                    record.stack_path,
                    record.duration_seconds,
                    record.file_size,
                    record.sha256,
                    record.added_chunks,
                    record.peak_before_guard,
                    record.peak_after_guard,
                    record.gain_reduction_db,
                ),
            )
        return record

    def _connect(self) -> sqlite3.Connection:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self._path)
        connection.row_factory = sqlite3.Row
        _ensure_schema(connection)
        return connection


def _ensure_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        create table if not exists stack_versions (
          id text primary key,
          kind text not null,
          created_at text not null,
          parent_version_id text,
          stack_path text not null,
          duration_seconds real not null,
          file_size integer not null,
          sha256 text not null,
          added_chunks integer not null,
          peak_before_guard real,
          peak_after_guard real,
          gain_reduction_db real
        )
        """
    )


def _record_from_row(row: sqlite3.Row) -> StackHistoryRecord:
    return StackHistoryRecord(
        id=str(row["id"]),
        kind=str(row["kind"]),
        created_at=str(row["created_at"]),
        parent_version_id=None
        if row["parent_version_id"] is None
        else str(row["parent_version_id"]),
        stack_path=str(row["stack_path"]),
        duration_seconds=float(row["duration_seconds"]),
        file_size=int(row["file_size"]),
        sha256=str(row["sha256"]),
        added_chunks=int(row["added_chunks"]),
        peak_before_guard=None
        if row["peak_before_guard"] is None
        else float(row["peak_before_guard"]),
        peak_after_guard=None
        if row["peak_after_guard"] is None
        else float(row["peak_after_guard"]),
        gain_reduction_db=None
        if row["gain_reduction_db"] is None
        else float(row["gain_reduction_db"]),
    )
