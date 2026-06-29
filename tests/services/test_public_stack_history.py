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


def test_stack_history_marks_deleted_versions_and_skips_them_for_latest(
    tmp_path: Path,
) -> None:
    store = StackHistoryStore(tmp_path / "history.sqlite3")
    seed = store.record_seed(
        stack_path="data/sources/voice/stack/seed.wav",
        duration_seconds=60.0,
        file_size=100,
        sha256="seed-sha",
    )
    first_commit = store.record_commit(
        parent_version_id=seed.id,
        stack_path="data/sources/voice/stack/commit-1.wav",
        duration_seconds=60.0,
        file_size=200,
        sha256="commit-1-sha",
        added_chunks=2,
        peak_before_guard=0.1,
        peak_after_guard=0.1,
        gain_reduction_db=0.0,
    )
    latest_commit = store.record_commit(
        parent_version_id=first_commit.id,
        stack_path="data/sources/voice/stack/commit-2.wav",
        duration_seconds=60.0,
        file_size=300,
        sha256="commit-2-sha",
        added_chunks=2,
        peak_before_guard=0.2,
        peak_after_guard=0.2,
        gain_reduction_db=0.0,
    )

    deleted = store.mark_deleted(latest_commit.id)

    records = store.list_versions()
    assert deleted is not None
    assert deleted.id == latest_commit.id
    assert deleted.deleted_at is not None
    assert records[0].deleted_at == deleted.deleted_at
    assert store.latest().id == first_commit.id


def test_stack_history_latest_returns_none_when_all_versions_are_deleted(
    tmp_path: Path,
) -> None:
    store = StackHistoryStore(tmp_path / "history.sqlite3")
    seed = store.record_seed(
        stack_path="data/sources/voice/stack/seed.wav",
        duration_seconds=60.0,
        file_size=100,
        sha256="seed-sha",
    )

    store.mark_deleted(seed.id)

    assert store.latest() is None
