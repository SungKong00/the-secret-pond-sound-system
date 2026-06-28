from __future__ import annotations

from pathlib import Path

from secret_pond.services.public_stack_history import StackHistoryStore


def test_stack_history_records_seed_and_commits(tmp_path: Path) -> None:
    store = StackHistoryStore(tmp_path / "history.sqlite3")

    seed = store.record_seed(
        stack_path="data/sources/voice/stack/seed.wav",
        duration_seconds=60.0,
        file_size=100,
        sha256="seed-sha",
    )
    commit = store.record_commit(
        parent_version_id=seed.id,
        stack_path="data/sources/voice/stack/commit.wav",
        duration_seconds=60.0,
        file_size=200,
        sha256="commit-sha",
        added_chunks=2,
        peak_before_guard=0.1,
        peak_after_guard=0.1,
        gain_reduction_db=0.0,
    )

    records = store.list_versions()

    assert [record.id for record in records] == [commit.id, seed.id]
    assert records[0].kind == "commit"
    assert records[0].parent_version_id == seed.id
    assert records[1].kind == "seed"
    assert store.latest().id == commit.id


def test_stack_history_gets_version_by_id(tmp_path: Path) -> None:
    store = StackHistoryStore(tmp_path / "history.sqlite3")
    record = store.record_seed(
        stack_path="data/sources/voice/stack/seed.wav",
        duration_seconds=60.0,
        file_size=100,
        sha256="seed-sha",
    )

    assert store.get(record.id) == record
