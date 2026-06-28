# Public Voice Stack Recorder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a short-lived mobile web recorder that lets invited users add their own recording to the latest Voice Stack without preserving individual voice files, while allowing the administrator to download every saved stack version by password.

**Architecture:** Add a separate public-recorder FastAPI app instead of exposing the existing operator dashboard. Reuse `ProjectPaths`, `SettingsStore`, `VoiceStackStore`, `AudioBuffer`, and `apply_recording_processing`, but add a small public upload service, a file lock, SQLite stack history, token-protected recording routes, and password-protected admin download routes. Deploy one Render web service with one persistent disk so all stack WAV versions and history survive restarts and redeploys.

**Tech Stack:** Python 3.11+, FastAPI, browser `getUserMedia` + `MediaRecorder`, FFmpeg, `soundfile`, NumPy/SciPy/Pedalboard, SQLite, `filelock`, Render Starter Web Service + 1 GB Persistent Disk.

---

## Captured Requirements

- Only the Voice Stack collection flow goes online. The full Secret Pond operator dashboard is not part of this release.
- Users access a private link without login.
- The public page supports mobile browsers.
- Users record in the browser, then choose whether to add the recording.
- Users can discard or re-record before adding.
- After the user presses add, the addition is final. There is no post-add rollback button.
- The UI must clearly state that individual voice files are not stored or exposed.
- The server may use the uploaded original as a temporary processing file, but it must delete that file on success and on failure.
- The server must not keep `Voice Raw` files for public submissions.
- Each accepted recording is added to the latest active Voice Stack at the moment the server lock is acquired.
- If another submission is being processed, later submissions wait, then retry against the latest active stack.
- Every committed stack version remains available to the administrator as history.
- Administrator access is password protected by server environment variables.
- Administrator features are limited to listing/downloading stack files and checking health/history.
- Initial stack is provided before users start recording.
- Expected use is around 20 users for 3 to 5 days.
- MVP excludes user preview playback after recording because the fastest reliable release is record, re-record, add.

## Current Code Evidence

- Existing stack semantics already match the privacy goal: `README.md` says `live_ephemeral` updates the Voice Stack directly without keeping individual Voice Raw or accepted chunk files.
- `src/secret_pond/audio/voice_stack.py` already writes timestamped Voice Stack sources under `data/sources/voice/stack/` and keeps `data/voice/voice_stack_raw.wav` as a compatibility mirror.
- `VoiceStackStore.add_processed_voice()` already splits long recordings, places chunks into the loop, peak-guards the result, writes a timestamped stack source, updates the manifest, and returns `voice_stack_path`.
- `src/secret_pond/services/controller.py` already applies recording processing, clears `voice_raw_path`, updates `voice_stack_path`, and persists selected stack paths in `live_ephemeral`.
- `src/secret_pond/services/recording_transaction.py` already snapshots and rolls back stack side effects for local recording. The public path should use the same safety principle around temporary upload files and settings/history writes.
- `src/secret_pond/app.py` builds the local operator runtime on startup. The public deployment should not use this app directly because Render will not have a show audio input/output device and should not expose operator controls.
- Runtime `data/` is ignored by git in `.gitignore`, so the initial stack must be seeded into the Render persistent disk, not committed into the repo.

## External References

- Browser microphone access: [MDN getUserMedia](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia)
- Browser recording API: [MDN MediaRecorder](https://developer.mozilla.org/en-US/docs/Web/API/MediaRecorder)
- FastAPI file uploads: [FastAPI Request Files](https://fastapi.tiangolo.com/tutorial/request-files/)
- FastAPI HTTP Basic Auth: [FastAPI HTTP Basic Auth](https://fastapi.tiangolo.com/advanced/security/http-basic-auth/)
- FastAPI file downloads: [FastAPI Custom Response - FileResponse](https://fastapi.tiangolo.com/advanced/custom-response/#fileresponse)
- Render persistent storage: [Render Disks](https://render.com/docs/disks)
- Render pricing: [Render Pricing](https://render.com/pricing)

## MVP Product Flow

```text
User opens /r/{public_token}
  -> grants microphone permission
  -> taps Record
  -> taps Stop
  -> chooses Re-record or Add to Voice Stack
  -> Add uploads one temporary recording blob
  -> server waits on stack lock
  -> server reloads latest active settings/stack inside the lock
  -> server decodes upload to WAV with FFmpeg
  -> server rejects oversized, too short, too long, undecodable, or processing-failed input
  -> server runs existing recording processing
  -> server adds processed audio to latest Voice Stack
  -> server saves stack version metadata
  -> server updates active stack path
  -> server deletes upload and decoded temp WAV
  -> user sees committed confirmation
```

```text
Admin opens /admin
  -> enters HTTP Basic username/password
  -> sees active stack and stack version history
  -> downloads latest stack or a selected historical version
```

## Storage Model

```text
data/
  public/
    stack_history.sqlite
    voice_stack.lock
  recordings_temp/
    public-upload-<uuid>.webm
    public-upload-<uuid>.wav
  sources/
    voice/
      stack/
        VS000000_seed.wav
        VS0628_153012.wav
        VS0628_153245.wav
      raw/
  voice/
    voice_stack_raw.wav
    voice_stack_manifest.json
  config/
    settings.json
```

Rules:

- `data/recordings_temp/public-upload-*` files exist only during one request and are removed in `finally`.
- FastAPI `UploadFile` objects must be closed in route `finally` blocks so any framework-level spooled temporary file is released.
- `data/sources/voice/raw/` remains empty for public submissions.
- `data/processed/accepted/` remains empty for public submissions.
- Each committed stack source under `data/sources/voice/stack/` is immutable.
- `data/voice/voice_stack_raw.wav` mirrors the latest stack.
- `settings.json` active and draft source paths both point at the latest stack after each public commit.
- SQLite history stores stack metadata only, never temporary upload paths.

## Concurrency Policy

Use a single Render instance and a process/file lock.

```text
lock_timeout_seconds = 30
lock_path = data/public/voice_stack.lock
```

Inside the lock:

1. Reload settings from disk.
2. Force `voice_stack.mode = "live_ephemeral"` for the public submission.
3. Read the active latest stack from settings or `voice_stack_raw.wav`.
4. Add the processed upload to that latest stack.
5. Save new active/draft source paths.
6. Insert one history row.

If the lock times out:

- Return a `lock_timeout` response and ask the user to retry.
- Delete upload temp files before returning.
- Do not create a stack history row.

This satisfies the requirement that late submissions do not fail just because a previous user was first; they wait and then add to the newest stack that exists when processing begins.

## Deployment Decision

Use Render paid Web Service with Persistent Disk for the MVP.

Recommended starting plan for 20 users over 3 to 5 days:

```text
Render Web Service: Starter
Persistent Disk: 1 GB
Workers: 1
Expected cost: about $7.25/month at the public pricing checked on 2026-06-28
```

Why this is the simplest fit:

- Render provides HTTPS, which mobile browser microphone APIs require.
- One web service can run FastAPI, FFmpeg, SQLite, and local persistent disk storage.
- One persistent disk avoids introducing S3/R2 credentials and object lifecycle rules for the MVP.
- One worker plus file lock keeps concurrency simple and predictable.

Avoid for this MVP:

- Vercel/Netlify serverless functions, because FFmpeg, persistent WAV history, and lock-based processing are awkward there.
- Multi-instance autoscaling, because SQLite and a local file lock are intentionally single-instance.
- Full operator dashboard hosting, because public deployment should not require audio hardware.

## File Structure

- Create: `src/secret_pond/public_app.py`
  - Public-recorder FastAPI app factory. Does not build the local operator runtime.
- Create: `src/secret_pond/services/public_settings.py`
  - Environment-backed public token, admin credentials, max upload size, and lock timeout config.
- Create: `src/secret_pond/services/public_stack_history.py`
  - SQLite schema and accessors for seed and committed stack versions.
- Create: `src/secret_pond/services/public_voice_stack.py`
  - Upload temp handling, FFmpeg decode, input validation, stack lock, existing DSP/VoiceStack integration, settings update, and cleanup.
- Create: `src/secret_pond/web/public_routes.py`
  - Token-protected recording page and submission endpoint.
- Create: `src/secret_pond/web/admin_routes.py`
  - HTTP Basic protected admin history page and stack download endpoints.
- Create: `src/secret_pond/web/static/public_recorder.html`
  - Minimal mobile recording UI.
- Create: `src/secret_pond/web/static/public_recorder.js`
  - `getUserMedia` and `MediaRecorder` controller.
- Create: `src/secret_pond/web/static/public_recorder.css`
  - Minimal responsive styling for mobile.
- Modify: `src/secret_pond/cli.py`
  - Add `public-recorder-serve` and `public-recorder-init-seed`.
- Modify: `src/secret_pond/paths.py`
  - Add `public_dir`, `public_history_file`, and `public_stack_lock_file`.
- Modify: `pyproject.toml`
  - Add `python-multipart` for FastAPI form uploads.
  - Add `filelock` for cross-platform file locking.
  - Include `secret_pond/web/static/*` as package data so Docker installs the public HTML, CSS, and JavaScript files.
- Create: `tests/services/test_public_stack_history.py`
- Create: `tests/services/test_public_voice_stack.py`
- Create: `tests/web/test_public_recorder_routes.py`
- Create: `tests/web/test_admin_stack_routes.py`
- Create: `Dockerfile.public-recorder`
- Create: `render.yaml`
- Create: `docs/operator-public-recorder.md`

## Task 1: Public Recorder Configuration and Paths

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/secret_pond/paths.py`
- Create: `src/secret_pond/services/public_settings.py`
- Test: `tests/services/test_public_settings.py`

- [ ] **Step 1: Add dependency test expectations**

Create `tests/services/test_public_settings.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from secret_pond.paths import ProjectPaths
from secret_pond.services.public_settings import PublicRecorderSettings


def test_public_paths_live_under_data_public(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path)

    assert paths.public_dir == tmp_path / "data" / "public"
    assert paths.public_history_file == tmp_path / "data" / "public" / "stack_history.sqlite"
    assert paths.public_stack_lock_file == tmp_path / "data" / "public" / "voice_stack.lock"


def test_public_settings_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PUBLIC_RECORDING_TOKEN", "record-token")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "secret-password")
    monkeypatch.setenv("PUBLIC_MAX_UPLOAD_BYTES", "123456")
    monkeypatch.setenv("PUBLIC_STACK_LOCK_TIMEOUT_SECONDS", "45")

    settings = PublicRecorderSettings.from_env()

    assert settings.public_recording_token == "record-token"
    assert settings.admin_username == "admin"
    assert settings.admin_password == "secret-password"
    assert settings.max_upload_bytes == 123456
    assert settings.stack_lock_timeout_seconds == 45.0


def test_public_settings_require_secret_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PUBLIC_RECORDING_TOKEN", raising=False)
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "secret-password")

    with pytest.raises(ValueError, match="PUBLIC_RECORDING_TOKEN"):
        PublicRecorderSettings.from_env()
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest tests/services/test_public_settings.py -q
```

Expected: fails because `PublicRecorderSettings` and public path properties do not exist.

- [ ] **Step 3: Add dependencies and static package data**

Modify `pyproject.toml` dependencies:

```toml
  "python-multipart>=0.0.9",
  "filelock>=3.15",
```

Add package data after `[tool.setuptools.packages.find]`:

```toml
[tool.setuptools.package-data]
secret_pond = ["web/static/*"]
```

- [ ] **Step 4: Add public data paths**

Modify `src/secret_pond/paths.py`:

```python
    @property
    def public_dir(self) -> Path:
        return self.data_dir / "public"

    @property
    def public_history_file(self) -> Path:
        return self.public_dir / "stack_history.sqlite"

    @property
    def public_stack_lock_file(self) -> Path:
        return self.public_dir / "voice_stack.lock"
```

Add `self.public_dir` to the tuple in `ensure_directories()`.

- [ ] **Step 5: Add environment-backed settings**

Create `src/secret_pond/services/public_settings.py`:

```python
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class PublicRecorderSettings:
    public_recording_token: str
    admin_username: str
    admin_password: str
    max_upload_bytes: int = 25 * 1024 * 1024
    stack_lock_timeout_seconds: float = 60.0

    @classmethod
    def from_env(cls) -> PublicRecorderSettings:
        return cls(
            public_recording_token=_required_env("PUBLIC_RECORDING_TOKEN"),
            admin_username=_required_env("ADMIN_USERNAME"),
            admin_password=_required_env("ADMIN_PASSWORD"),
            max_upload_bytes=int(os.environ.get("PUBLIC_MAX_UPLOAD_BYTES", 25 * 1024 * 1024)),
            stack_lock_timeout_seconds=float(
                os.environ.get("PUBLIC_STACK_LOCK_TIMEOUT_SECONDS", 60.0)
            ),
        )


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        msg = f"{name} must be set"
        raise ValueError(msg)
    return value
```

- [ ] **Step 6: Run test to verify it passes**

Run:

```bash
uv run pytest tests/services/test_public_settings.py -q
```

Expected: passes.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml src/secret_pond/paths.py src/secret_pond/services/public_settings.py tests/services/test_public_settings.py
git commit -m "feat: add public recorder configuration"
```

## Task 2: Stack History Store

**Files:**
- Create: `src/secret_pond/services/public_stack_history.py`
- Test: `tests/services/test_public_stack_history.py`

- [ ] **Step 1: Write failing tests**

Create `tests/services/test_public_stack_history.py`:

```python
from __future__ import annotations

from pathlib import Path

from secret_pond.services.public_stack_history import StackHistoryRecord, StackHistoryStore


def test_stack_history_records_seed_and_commits(tmp_path: Path) -> None:
    db_path = tmp_path / "stack_history.sqlite"
    store = StackHistoryStore(db_path)

    seed = store.record_seed(
        stack_path="data/sources/voice/stack/VS000000_seed.wav",
        duration_seconds=60.0,
        file_size=100,
        sha256="a" * 64,
    )
    commit = store.record_commit(
        parent_version_id=seed.id,
        stack_path="data/sources/voice/stack/VS0628_153012.wav",
        duration_seconds=60.0,
        file_size=120,
        sha256="b" * 64,
        added_chunks=1,
        peak_before_guard=0.4,
        peak_after_guard=0.4,
        gain_reduction_db=0.0,
    )

    records = store.list_versions()

    assert [record.id for record in records] == [commit.id, seed.id]
    assert records[0].kind == "commit"
    assert records[0].parent_version_id == seed.id
    assert store.latest() == commit


def test_stack_history_gets_version_by_id(tmp_path: Path) -> None:
    store = StackHistoryStore(tmp_path / "stack_history.sqlite")
    record = store.record_seed(
        stack_path="data/sources/voice/stack/VS000000_seed.wav",
        duration_seconds=60.0,
        file_size=100,
        sha256="a" * 64,
    )

    assert store.get(record.id) == record
    assert store.get("missing") is None


def test_stack_history_dataclass_is_hash_safe() -> None:
    record = StackHistoryRecord(
        id="version-id",
        kind="seed",
        created_at="2026-06-28T00:00:00+00:00",
        parent_version_id=None,
        stack_path="data/sources/voice/stack/VS000000_seed.wav",
        duration_seconds=60.0,
        file_size=100,
        sha256="a" * 64,
        added_chunks=0,
        peak_before_guard=0.0,
        peak_after_guard=0.0,
        gain_reduction_db=0.0,
    )

    assert record.id == "version-id"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest tests/services/test_public_stack_history.py -q
```

Expected: fails because `public_stack_history.py` does not exist.

- [ ] **Step 3: Implement SQLite history**

Create `src/secret_pond/services/public_stack_history.py`:

```python
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
    peak_before_guard: float
    peak_after_guard: float
    gain_reduction_db: float


class StackHistoryStore:
    def __init__(self, db_path: Path) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

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
            peak_before_guard=0.0,
            peak_after_guard=0.0,
            gain_reduction_db=0.0,
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
        with self._connect() as conn:
            row = conn.execute(
                "select * from stack_versions order by created_at desc, rowid desc limit 1"
            ).fetchone()
        return None if row is None else _record_from_row(row)

    def list_versions(self) -> list[StackHistoryRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "select * from stack_versions order by created_at desc, rowid desc"
            ).fetchall()
        return [_record_from_row(row) for row in rows]

    def get(self, version_id: str) -> StackHistoryRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "select * from stack_versions where id = ?",
                (version_id,),
            ).fetchone()
        return None if row is None else _record_from_row(row)

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
        peak_before_guard: float,
        peak_after_guard: float,
        gain_reduction_db: float,
    ) -> StackHistoryRecord:
        record = StackHistoryRecord(
            id=uuid4().hex,
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
        with self._connect() as conn:
            conn.execute(
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
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                create table if not exists stack_versions (
                  id text primary key,
                  kind text not null check(kind in ('seed', 'commit')),
                  created_at text not null,
                  parent_version_id text,
                  stack_path text not null,
                  duration_seconds real not null,
                  file_size integer not null,
                  sha256 text not null,
                  added_chunks integer not null,
                  peak_before_guard real not null,
                  peak_after_guard real not null,
                  gain_reduction_db real not null
                )
                """
            )


def _record_from_row(row: sqlite3.Row) -> StackHistoryRecord:
    return StackHistoryRecord(
        id=str(row["id"]),
        kind=str(row["kind"]),
        created_at=str(row["created_at"]),
        parent_version_id=row["parent_version_id"],
        stack_path=str(row["stack_path"]),
        duration_seconds=float(row["duration_seconds"]),
        file_size=int(row["file_size"]),
        sha256=str(row["sha256"]),
        added_chunks=int(row["added_chunks"]),
        peak_before_guard=float(row["peak_before_guard"]),
        peak_after_guard=float(row["peak_after_guard"]),
        gain_reduction_db=float(row["gain_reduction_db"]),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
uv run pytest tests/services/test_public_stack_history.py -q
```

Expected: passes.

- [ ] **Step 5: Commit**

```bash
git add src/secret_pond/services/public_stack_history.py tests/services/test_public_stack_history.py
git commit -m "feat: track public voice stack history"
```

## Task 3: Public Voice Stack Processing Service

**Files:**
- Create: `src/secret_pond/services/public_voice_stack.py`
- Test: `tests/services/test_public_voice_stack.py`

- [ ] **Step 1: Write failing tests for temp cleanup and no raw retention**

Create `tests/services/test_public_voice_stack.py`:

```python
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from filelock import FileLock

from secret_pond.audio.buffers import AudioBuffer
from secret_pond.audio.file_io import read_wav, write_wav_atomic
from secret_pond.config import (
    AppSettings,
    AudioFormatSettings,
    InputControlSettings,
    RecordingProcessingSettings,
    VoiceStackSettings,
)
from secret_pond.paths import ProjectPaths
from secret_pond.services.public_settings import PublicRecorderSettings
from secret_pond.services.public_stack_history import StackHistoryStore
from secret_pond.services.public_voice_stack import PublicVoiceStackService
from secret_pond.services.settings_store import SettingsState, SettingsStore


def public_settings() -> AppSettings:
    return AppSettings(
        audio=AudioFormatSettings(sample_rate=8_000, channels=2, loop_seconds=1),
        input_control=InputControlSettings(minimum_recording_seconds=3.0, maximum_recording_seconds=600.0),
        recording=RecordingProcessingSettings(
            gain_db=0.0,
            normalize_peak=0.2,
            highpass_hz=80.0,
            lowpass_hz=3_000.0,
            presence_gain_db=0.0,
            reverb_mix=0.0,
            delay_mix=0.0,
            fade_ms=0,
        ),
        voice_stack=VoiceStackSettings(mode="live_ephemeral", loop_seconds=1, insert_gain_db=0.0),
    )


def write_take(path: Path, *, amplitude: float = 0.05) -> None:
    sample_rate = 8_000
    frames = sample_rate // 2
    t = np.arange(frames, dtype=np.float32) / sample_rate
    tone = np.sin(2 * np.pi * 440.0 * t).astype(np.float32) * amplitude
    write_wav_atomic(path, AudioBuffer(samples=np.column_stack([tone, tone]), sample_rate=sample_rate))


def service(tmp_path: Path, *, lock_timeout: float = 1.0) -> PublicVoiceStackService:
    paths = ProjectPaths(tmp_path)
    settings = public_settings()
    SettingsStore(paths).save(SettingsState(active=settings, draft=settings))
    return PublicVoiceStackService(
        paths=paths,
        settings_store=SettingsStore(paths),
        history_store=StackHistoryStore(paths.public_history_file),
        public_settings=PublicRecorderSettings(
            public_recording_token="record-token",
            admin_username="admin",
            admin_password="secret-password",
            max_upload_bytes=25 * 1024 * 1024,
            stack_lock_timeout_seconds=lock_timeout,
        ),
    )


def test_public_recording_adds_latest_stack_without_voice_raw(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path)
    upload = tmp_path / "upload.wav"
    write_take(upload)

    result = service(tmp_path).add_decoded_wav(upload)

    assert result.history_record.stack_path.startswith("data/sources/voice/stack/")
    assert (tmp_path / result.history_record.stack_path).exists()
    assert paths.voice_stack_raw.exists()
    assert list(paths.voice_raw_sources_dir.glob("*.wav")) == []
    assert list(paths.accepted_dir.glob("*.wav")) == []
    stored = SettingsStore(paths).load()
    assert stored.active.sources.voice_raw_path is None
    assert stored.active.sources.voice_stack_path == result.history_record.stack_path
    assert read_wav(paths.voice_stack_raw).frames == 8_000


def test_public_recording_second_commit_uses_first_commit_as_parent(tmp_path: Path) -> None:
    first_upload = tmp_path / "first.wav"
    second_upload = tmp_path / "second.wav"
    write_take(first_upload, amplitude=0.04)
    write_take(second_upload, amplitude=0.06)
    stack_service = service(tmp_path)

    first = stack_service.add_decoded_wav(first_upload)
    second = stack_service.add_decoded_wav(second_upload)
    records = StackHistoryStore(ProjectPaths(tmp_path).public_history_file).list_versions()

    assert second.history_record.parent_version_id == first.history_record.id
    assert [record.id for record in records] == [
        second.history_record.id,
        first.history_record.id,
    ]
    assert first.history_record.stack_path != second.history_record.stack_path


def test_public_recording_deletes_temp_files_when_validation_fails(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path)
    upload = tmp_path / "too-short.wav"
    write_take(upload, seconds=1.0)

    with pytest.raises(PublicVoiceStackError, match="too_short"):
        service(tmp_path).add_decoded_wav(upload)

    assert upload.exists()
    assert list(paths.voice_raw_sources_dir.glob("*.wav")) == []
    assert list(paths.accepted_dir.glob("*.wav")) == []
    assert StackHistoryStore(paths.public_history_file).list_versions() == []


def test_public_recording_times_out_when_stack_lock_is_held(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path)
    upload = tmp_path / "upload.wav"
    write_take(upload)
    stack_service = service(tmp_path, lock_timeout=0.01)

    with FileLock(paths.public_stack_lock_file, timeout=0):
        with pytest.raises(PublicVoiceStackError, match="lock_timeout"):
            stack_service.add_decoded_wav(upload)

    assert StackHistoryStore(paths.public_history_file).list_versions() == []


def test_public_recording_restores_stack_when_history_write_fails(tmp_path: Path) -> None:
    class FailingHistoryStore(StackHistoryStore):
        def record_commit(self, **kwargs):
            raise OSError("history write failed")

    paths = ProjectPaths(tmp_path)
    upload = tmp_path / "upload.wav"
    write_take(upload)
    settings = public_settings()
    SettingsStore(paths).save(SettingsState(active=settings, draft=settings))
    stack_service = PublicVoiceStackService(
        paths=paths,
        settings_store=SettingsStore(paths),
        history_store=FailingHistoryStore(paths.public_history_file),
        public_settings=PublicRecorderSettings(
            public_recording_token="record-token",
            admin_username="admin",
            admin_password="secret-password",
            max_upload_bytes=25 * 1024 * 1024,
            stack_lock_timeout_seconds=1.0,
        ),
    )

    with pytest.raises(OSError, match="history write failed"):
        stack_service.add_decoded_wav(upload)

    stored = SettingsStore(paths).load()
    assert stored.active.sources.voice_stack_path is None
    assert list(paths.voice_stack_sources_dir.glob("*.wav")) == []
    assert list(paths.voice_raw_sources_dir.glob("*.wav")) == []
    assert list(paths.accepted_dir.glob("*.wav")) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest tests/services/test_public_voice_stack.py -q
```

Expected: fails because `PublicVoiceStackService` does not exist.

- [ ] **Step 3: Implement public processing service**

Create `src/secret_pond/services/public_voice_stack.py`:

```python
from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from filelock import FileLock, Timeout

from secret_pond.audio.effects import apply_recording_processing
from secret_pond.audio.file_io import read_wav, write_wav_atomic
from secret_pond.audio.voice_stack import VoiceStackAddResult, VoiceStackStore
from secret_pond.config import AppSettings
from secret_pond.paths import ProjectPaths
from secret_pond.services.file_snapshots import (
    FileSnapshot,
    capture_file_snapshot,
    restore_file_snapshot,
)
from secret_pond.services.public_settings import PublicRecorderSettings
from secret_pond.services.public_stack_history import StackHistoryRecord, StackHistoryStore
from secret_pond.services.recording_processing_policy import recording_processing_sample_rate
from secret_pond.services.settings_store import SettingsState, SettingsStore


@dataclass(frozen=True)
class PublicVoiceStackResult:
    history_record: StackHistoryRecord
    stack_result: VoiceStackAddResult


@dataclass(frozen=True)
class PublicStackSideEffectSnapshot:
    voice_stack_raw: FileSnapshot
    voice_manifest: FileSnapshot
    voice_stack_files: set[Path]
    voice_raw_files: set[Path]
    accepted_files: set[Path]
    settings_state: SettingsState


class PublicVoiceStackService:
    def __init__(
        self,
        *,
        paths: ProjectPaths,
        settings_store: SettingsStore,
        history_store: StackHistoryStore,
        public_settings: PublicRecorderSettings,
    ) -> None:
        self._paths = paths
        self._paths.ensure_directories()
        self._settings_store = settings_store
        self._history_store = history_store
        self._public_settings = public_settings
        self._voice_stack = VoiceStackStore(paths)

    def decode_upload_to_wav(self, upload_path: Path) -> Path:
        if upload_path.suffix.lower() == ".wav":
            return upload_path
        wav_path = self._paths.recordings_temp_dir / f"public-upload-{uuid4().hex}.wav"
        wav_path.parent.mkdir(parents=True, exist_ok=True)
        command = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(upload_path),
            "-acodec",
            "pcm_s16le",
            str(wav_path),
        ]
        subprocess.run(command, check=True)
        return wav_path

    def add_decoded_wav(self, wav_path: Path) -> PublicVoiceStackResult:
        try:
            with FileLock(
                self._paths.public_stack_lock_file,
                timeout=self._public_settings.stack_lock_timeout_seconds,
            ):
                return self._add_decoded_wav_inside_lock(wav_path)
        except Timeout as exc:
            raise PublicVoiceStackError("lock_timeout") from exc

    def _add_decoded_wav_inside_lock(self, wav_path: Path) -> PublicVoiceStackResult:
        current = self._settings_store.load()
        active = _public_active_settings(current.active)
        loaded = read_wav(wav_path)
        canonical = loaded.to_canonical(
            sample_rate=recording_processing_sample_rate(active, loaded.sample_rate),
            channels=active.audio.channels,
        )
        duration_seconds = canonical.frames / canonical.sample_rate if canonical.sample_rate else 0.0
        if duration_seconds < active.input_control.minimum_recording_seconds:
            msg = "recording is too short"
            raise ValueError(msg)
        if duration_seconds > self._public_settings.maximum_duration_seconds:
            raise PublicVoiceStackError("too_long")

        snapshot = _capture_public_side_effects(self._paths, self._settings_store)
        try:
            processed = apply_recording_processing(canonical, active.recording)
            latest_before = self._history_store.latest()
            stack_result = self._voice_stack.add_processed_voice(
                processed,
                active,
                processing_settings_snapshot=active.recording.model_dump(mode="json"),
            )
            active.sources.voice_raw_path = None
            if stack_result.voice_stack_path is not None:
                active.sources.voice_stack_path = stack_result.voice_stack_path

            draft = current.draft.model_copy(
                update={
                    "voice_stack": active.voice_stack,
                    "sources": current.draft.sources.model_copy(
                        update={
                            "voice_raw_path": None,
                            "voice_stack_path": active.sources.voice_stack_path,
                        }
                    ),
                },
                deep=True,
            )
            self._settings_store.save(SettingsState(active=active, draft=draft))

            stack_path = active.sources.voice_stack_path
            if stack_path is None:
                msg = "voice stack path was not created"
                raise RuntimeError(msg)
            absolute_stack_path = self._paths.root / stack_path
            record = self._history_store.record_commit(
                parent_version_id=None if latest_before is None else latest_before.id,
                stack_path=stack_path,
                duration_seconds=duration_seconds,
                file_size=absolute_stack_path.stat().st_size,
                sha256=_sha256_file(absolute_stack_path),
                added_chunks=stack_result.added_chunks,
                peak_before_guard=stack_result.peak_before_guard,
                peak_after_guard=stack_result.peak_after_guard,
                gain_reduction_db=stack_result.gain_reduction_db,
            )
            return PublicVoiceStackResult(history_record=record, stack_result=stack_result)
        except Exception as exc:
            try:
                _restore_public_side_effects(self._paths, self._settings_store, snapshot)
            except Exception as rollback_exc:
                msg = f"{exc}; rollback failed: {rollback_exc}"
                raise RuntimeError(msg) from exc
            raise


def _public_active_settings(settings: AppSettings) -> AppSettings:
    return settings.model_copy(
        update={
            "voice_stack": settings.voice_stack.model_copy(update={"mode": "live_ephemeral"}),
            "sources": settings.sources.model_copy(update={"voice_raw_path": None}),
        },
        deep=True,
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _capture_public_side_effects(
    paths: ProjectPaths,
    settings_store: SettingsStore,
) -> PublicStackSideEffectSnapshot:
    current = settings_store.load()
    return PublicStackSideEffectSnapshot(
        voice_stack_raw=capture_file_snapshot(paths.voice_stack_raw),
        voice_manifest=capture_file_snapshot(paths.voice_manifest),
        voice_stack_files=set(paths.voice_stack_sources_dir.glob("*.wav")),
        voice_raw_files=set(paths.voice_raw_sources_dir.glob("*.wav")),
        accepted_files=set(paths.accepted_dir.glob("*.wav")),
        settings_state=SettingsState(
            active=current.active.model_copy(deep=True),
            draft=current.draft.model_copy(deep=True),
        ),
    )


def _restore_public_side_effects(
    paths: ProjectPaths,
    settings_store: SettingsStore,
    snapshot: PublicStackSideEffectSnapshot,
) -> None:
    restore_file_snapshot(paths.voice_stack_raw, snapshot.voice_stack_raw)
    restore_file_snapshot(paths.voice_manifest, snapshot.voice_manifest)
    _remove_new_wavs(paths.voice_stack_sources_dir, snapshot.voice_stack_files)
    _remove_new_wavs(paths.voice_raw_sources_dir, snapshot.voice_raw_files)
    _remove_new_wavs(paths.accepted_dir, snapshot.accepted_files)
    settings_store.save(snapshot.settings_state)


def _remove_new_wavs(directory: Path, before: set[Path]) -> None:
    for path in set(directory.glob("*.wav")) - before:
        path.unlink(missing_ok=True)
```

- [ ] **Step 4: Add upload temp cleanup helper**

Extend `PublicVoiceStackService` with:

```python
    def add_upload_file(self, upload_path: Path) -> PublicVoiceStackResult:
        wav_path: Path | None = None
        try:
            wav_path = self.decode_upload_to_wav(upload_path)
            return self.add_decoded_wav(wav_path)
        finally:
            upload_path.unlink(missing_ok=True)
            if wav_path is not None:
                wav_path.unlink(missing_ok=True)
```

- [ ] **Step 5: Run tests**

Run:

```bash
uv run pytest tests/services/test_public_voice_stack.py tests/services/test_public_stack_history.py -q
```

Expected: passes.

- [ ] **Step 6: Commit**

```bash
git add src/secret_pond/services/public_voice_stack.py tests/services/test_public_voice_stack.py
git commit -m "feat: add public voice stack processor"
```

## Task 4: Public Recording Page and Submission API

**Files:**
- Create: `src/secret_pond/web/public_routes.py`
- Create: `src/secret_pond/web/static/public_recorder.html`
- Create: `src/secret_pond/web/static/public_recorder.js`
- Create: `src/secret_pond/web/static/public_recorder.css`
- Test: `tests/web/test_public_recorder_routes.py`

- [ ] **Step 1: Write failing route tests**

Create `tests/web/test_public_recorder_routes.py`:

```python
from __future__ import annotations

from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient

from secret_pond.audio.buffers import AudioBuffer
from secret_pond.audio.file_io import write_wav_atomic
from secret_pond.config import AppSettings, AudioFormatSettings, InputControlSettings, VoiceStackSettings
from secret_pond.paths import ProjectPaths
from secret_pond.public_app import create_public_app
from secret_pond.services.public_settings import PublicRecorderSettings
from secret_pond.services.settings_store import SettingsState, SettingsStore


def public_settings() -> PublicRecorderSettings:
    return PublicRecorderSettings(
        public_recording_token="record-token",
        admin_username="admin",
        admin_password="secret-password",
        max_upload_bytes=25 * 1024 * 1024,
        stack_lock_timeout_seconds=1.0,
    )


def client(tmp_path: Path) -> TestClient:
    settings = AppSettings(
        audio=AudioFormatSettings(sample_rate=8_000, channels=2, loop_seconds=1),
        input_control=InputControlSettings(minimum_recording_seconds=3.0, maximum_recording_seconds=600.0),
        voice_stack=VoiceStackSettings(mode="live_ephemeral", loop_seconds=1, insert_gain_db=0.0),
    )
    SettingsStore(ProjectPaths(tmp_path)).save(SettingsState(active=settings, draft=settings))
    return TestClient(create_public_app(root=tmp_path, public_settings=public_settings()))


def test_public_recording_page_requires_token(tmp_path: Path) -> None:
    app = client(tmp_path)

    assert app.get("/r/wrong-token").status_code == 404
    response = app.get("/r/record-token")

    assert response.status_code == 200
    assert "녹음 원본은" in response.text
    assert "public_recorder.js" in response.text


def test_public_recording_upload_requires_token(tmp_path: Path) -> None:
    upload = tmp_path / "take.wav"
    frames = 4_000
    tone = np.ones((frames, 2), dtype=np.float32) * 0.05
    write_wav_atomic(upload, AudioBuffer(samples=tone, sample_rate=8_000))

    with upload.open("rb") as handle:
        response = client(tmp_path).post(
            "/api/public/recordings",
            data={"token": "wrong-token"},
            files={"file": ("take.wav", handle, "audio/wav")},
        )

    assert response.status_code == 404


def test_public_recording_upload_commits_stack_and_deletes_raw(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path)
    upload = tmp_path / "take.wav"
    frames = 4_000
    tone = np.ones((frames, 2), dtype=np.float32) * 0.05
    write_wav_atomic(upload, AudioBuffer(samples=tone, sample_rate=8_000))

    with upload.open("rb") as handle:
        response = client(tmp_path).post(
            "/api/public/recordings",
            data={"token": "record-token"},
            files={"file": ("take.wav", handle, "audio/wav")},
        )

    assert response.status_code == 201
    assert response.json()["accepted"] is True
    assert response.json()["stack_version_id"]
    assert list(paths.voice_raw_sources_dir.glob("*.wav")) == []
    assert list(paths.recordings_temp_dir.glob("public-upload-*")) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest tests/web/test_public_recorder_routes.py -q
```

Expected: fails because public app and routes do not exist.

- [ ] **Step 3: Add public route handlers**

Create `src/secret_pond/web/public_routes.py`:

```python
from __future__ import annotations

import subprocess
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from secret_pond.paths import ProjectPaths
from secret_pond.services.public_settings import PublicRecorderSettings
from secret_pond.services.public_stack_history import StackHistoryStore
from secret_pond.services.public_voice_stack import PublicVoiceStackService
from secret_pond.services.settings_store import SettingsStore

router = APIRouter()
STATIC_DIR = Path(__file__).resolve().parent / "static"


@router.get("/r/{token}", include_in_schema=False)
def public_recorder_page(token: str, request: Request) -> FileResponse:
    settings = _public_settings(request)
    if token != settings.public_recording_token:
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(STATIC_DIR / "public_recorder.html")


@router.post("/api/public/recordings", status_code=201)
async def submit_public_recording(
    request: Request,
    token: str = Form(...),
    file: UploadFile = File(...),
) -> dict[str, object]:
    try:
        settings = _public_settings(request)
        if token != settings.public_recording_token:
            raise HTTPException(status_code=404, detail="not found")
        content = await file.read(settings.max_upload_bytes + 1)
        if len(content) > settings.max_upload_bytes:
            raise HTTPException(status_code=413, detail="녹음 파일이 너무 큽니다.")

        paths = ProjectPaths(request.app.state.root)
        paths.ensure_directories()
        extension = _extension_for_upload(file)
        upload_path = paths.recordings_temp_dir / f"public-upload-{uuid4().hex}{extension}"
        upload_path.write_bytes(content)

        service = PublicVoiceStackService(
            paths=paths,
            settings_store=SettingsStore(paths),
            history_store=StackHistoryStore(paths.public_history_file),
            public_settings=settings,
        )
        try:
            result = service.add_upload_file(upload_path)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except subprocess.CalledProcessError as exc:
            raise HTTPException(status_code=422, detail="녹음 파일을 읽을 수 없습니다.") from exc
        except OSError as exc:
            raise HTTPException(status_code=409, detail="녹음 파일 처리에 실패했습니다.") from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return {
            "accepted": True,
            "stack_version_id": result.history_record.id,
            "stack_path": result.history_record.stack_path,
            "message": "목소리 스택에 추가되었습니다. 추가 후에는 취소할 수 없습니다.",
        }
    finally:
        await file.close()


def _extension_for_upload(file: UploadFile) -> str:
    content_type = (file.content_type or "").lower()
    if "wav" in content_type:
        return ".wav"
    if "mp4" in content_type or "mpeg" in content_type:
        return ".mp4"
    return ".webm"


def _public_settings(request: Request) -> PublicRecorderSettings:
    return request.app.state.public_settings
```

- [ ] **Step 4: Add minimal public HTML**

Create `src/secret_pond/web/static/public_recorder.html`:

```html
<!doctype html>
<html lang="ko">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Secret Pond Voice Stack</title>
    <link rel="stylesheet" href="/static/public_recorder.css" />
  </head>
  <body>
    <main class="recorder-shell">
      <h1>목소리 스택 녹음</h1>
      <p class="privacy">
        녹음 원본은 목소리 스택에 추가하기 위해 임시로만 처리되며,
        개별 음성 파일로 저장되거나 관리자에게 제공되지 않습니다.
        스택에 추가한 뒤에는 취소할 수 없습니다.
      </p>
      <section class="panel">
        <div id="status" class="status">대기 중</div>
        <button id="recordButton" type="button">녹음 시작</button>
        <button id="stopButton" type="button" disabled>정지</button>
        <button id="retryButton" type="button" disabled>다시 녹음</button>
        <button id="submitButton" type="button" disabled>스택에 추가</button>
      </section>
    </main>
    <script src="/static/public_recorder.js"></script>
  </body>
</html>
```

- [ ] **Step 5: Add mobile recorder JavaScript**

Create `src/secret_pond/web/static/public_recorder.js`:

```javascript
const token = decodeURIComponent(window.location.pathname.split("/").pop() || "");
const statusEl = document.getElementById("status");
const recordButton = document.getElementById("recordButton");
const stopButton = document.getElementById("stopButton");
const retryButton = document.getElementById("retryButton");
const submitButton = document.getElementById("submitButton");

let recorder = null;
let stream = null;
let chunks = [];
let recordedBlob = null;

const setStatus = (text) => {
  statusEl.textContent = text;
};

const supportedMimeType = () => {
  if (!window.MediaRecorder) return "";
  const candidates = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"];
  return candidates.find((type) => MediaRecorder.isTypeSupported(type)) || "";
};

recordButton.addEventListener("click", async () => {
  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
    setStatus("이 브라우저에서는 녹음을 사용할 수 없습니다. 다른 모바일 브라우저로 열어주세요.");
    return;
  }
  try {
    recordedBlob = null;
    chunks = [];
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const mimeType = supportedMimeType();
    recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
    recorder.addEventListener("dataavailable", (event) => {
      if (event.data.size > 0) chunks.push(event.data);
    });
    recorder.addEventListener("stop", () => {
      recordedBlob = new Blob(chunks, { type: recorder.mimeType || "audio/webm" });
      stream.getTracks().forEach((track) => track.stop());
      recordButton.disabled = true;
      stopButton.disabled = true;
      retryButton.disabled = false;
      submitButton.disabled = false;
      setStatus("녹음 완료. 다시 녹음하거나 스택에 추가할 수 있습니다.");
    });
    recorder.start();
    recordButton.disabled = true;
    stopButton.disabled = false;
    retryButton.disabled = true;
    submitButton.disabled = true;
    setStatus("녹음 중");
  } catch (error) {
    if (stream) stream.getTracks().forEach((track) => track.stop());
    recordButton.disabled = false;
    stopButton.disabled = true;
    retryButton.disabled = true;
    submitButton.disabled = true;
    setStatus("마이크 권한을 확인한 뒤 다시 시도해주세요.");
  }
});

stopButton.addEventListener("click", () => {
  if (recorder && recorder.state === "recording") recorder.stop();
});

retryButton.addEventListener("click", () => {
  recordedBlob = null;
  chunks = [];
  recordButton.disabled = false;
  stopButton.disabled = true;
  retryButton.disabled = true;
  submitButton.disabled = true;
  setStatus("대기 중");
});

submitButton.addEventListener("click", async () => {
  if (!recordedBlob) return;
  submitButton.disabled = true;
  retryButton.disabled = true;
  setStatus("스택에 추가 중");
  const form = new FormData();
  form.append("token", token);
  form.append("file", recordedBlob, "recording.webm");
  try {
    const response = await fetch("/api/public/recordings", { method: "POST", body: form });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      retryButton.disabled = false;
      submitButton.disabled = false;
      setStatus(payload.detail || "추가에 실패했습니다. 다시 시도해주세요.");
      return;
    }
    recordedBlob = null;
    setStatus(payload.message || "목소리 스택에 추가되었습니다.");
  } catch (error) {
    retryButton.disabled = false;
    submitButton.disabled = false;
    setStatus("네트워크 연결을 확인한 뒤 다시 시도해주세요.");
  }
});
```

- [ ] **Step 6: Add minimal CSS**

Create `src/secret_pond/web/static/public_recorder.css`:

```css
body {
  margin: 0;
  font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  background: #101418;
  color: #f5f7fa;
}

.recorder-shell {
  width: min(100% - 32px, 520px);
  margin: 0 auto;
  padding: 32px 0;
}

h1 {
  font-size: 28px;
  margin: 0 0 16px;
}

.privacy {
  color: #c6d0dc;
  line-height: 1.6;
}

.panel {
  display: grid;
  gap: 12px;
  margin-top: 24px;
}

.status {
  min-height: 24px;
  color: #dce8f5;
}

button {
  min-height: 48px;
  border: 1px solid #52606d;
  border-radius: 8px;
  background: #f5f7fa;
  color: #101418;
  font-size: 16px;
  font-weight: 700;
}

button:disabled {
  opacity: 0.45;
}
```

- [ ] **Step 7: Run route tests**

Run:

```bash
uv run pytest tests/web/test_public_recorder_routes.py -q
```

Expected: passes.

- [ ] **Step 8: Commit**

```bash
git add src/secret_pond/web/public_routes.py src/secret_pond/web/static/public_recorder.html src/secret_pond/web/static/public_recorder.js src/secret_pond/web/static/public_recorder.css tests/web/test_public_recorder_routes.py
git commit -m "feat: add public voice recorder page"
```

## Task 5: Admin Password Download

**Files:**
- Create: `src/secret_pond/web/admin_routes.py`
- Test: `tests/web/test_admin_stack_routes.py`

- [ ] **Step 1: Write failing admin tests**

Create `tests/web/test_admin_stack_routes.py`:

```python
from __future__ import annotations

import base64
from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient

from secret_pond.audio.buffers import AudioBuffer
from secret_pond.audio.file_io import write_wav_atomic
from secret_pond.paths import ProjectPaths
from secret_pond.public_app import create_public_app
from secret_pond.services.public_settings import PublicRecorderSettings
from secret_pond.services.public_stack_history import StackHistoryStore


def auth_header() -> dict[str, str]:
    token = base64.b64encode(b"admin:secret-password").decode("ascii")
    return {"Authorization": f"Basic {token}"}


def client(tmp_path: Path) -> TestClient:
    return TestClient(
        create_public_app(
            root=tmp_path,
            public_settings=PublicRecorderSettings(
                public_recording_token="record-token",
                admin_username="admin",
                admin_password="secret-password",
            ),
        )
    )


def seed_history(tmp_path: Path) -> str:
    paths = ProjectPaths(tmp_path)
    paths.ensure_directories()
    stack_path = paths.voice_stack_sources_dir / "VS000000_seed.wav"
    write_wav_atomic(
        stack_path,
        AudioBuffer(samples=np.zeros((8_000, 2), dtype=np.float32), sample_rate=8_000),
    )
    record = StackHistoryStore(paths.public_history_file).record_seed(
        stack_path="data/sources/voice/stack/VS000000_seed.wav",
        duration_seconds=1.0,
        file_size=stack_path.stat().st_size,
        sha256="a" * 64,
    )
    return record.id


def test_admin_requires_basic_auth(tmp_path: Path) -> None:
    response = client(tmp_path).get("/admin")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Basic"


def test_admin_lists_versions(tmp_path: Path) -> None:
    seed_history(tmp_path)

    response = client(tmp_path).get("/admin", headers=auth_header())

    assert response.status_code == 200
    assert "VS000000_seed.wav" in response.text
    assert "Latest stack" in response.text


def test_admin_downloads_version(tmp_path: Path) -> None:
    version_id = seed_history(tmp_path)

    response = client(tmp_path).get(f"/admin/stacks/{version_id}.wav", headers=auth_header())

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("audio/wav")
    assert response.content
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest tests/web/test_admin_stack_routes.py -q
```

Expected: fails because admin routes do not exist.

- [ ] **Step 3: Implement HTTP Basic admin routes**

Create `src/secret_pond/web/admin_routes.py`:

```python
from __future__ import annotations

import html
import secrets
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from secret_pond.paths import ProjectPaths
from secret_pond.services.public_settings import PublicRecorderSettings
from secret_pond.services.public_stack_history import StackHistoryRecord, StackHistoryStore

router = APIRouter()
security = HTTPBasic()


@router.get("/admin", response_class=HTMLResponse, include_in_schema=False)
def admin_page(
    request: Request,
    _: HTTPBasicCredentials = Depends(_admin_credentials),
) -> HTMLResponse:
    paths = ProjectPaths(request.app.state.root)
    store = StackHistoryStore(paths.public_history_file)
    records = store.list_versions()
    rows = "\n".join(_record_row(record) for record in records)
    body = f"""
    <!doctype html>
    <html lang="ko">
      <head><meta charset="utf-8" /><title>Voice Stack Admin</title></head>
      <body>
        <h1>Voice Stack Admin</h1>
        <p><a href="/admin/stacks/latest.wav">Latest stack</a></p>
        <table>
          <thead><tr><th>created</th><th>kind</th><th>file</th><th>download</th></tr></thead>
          <tbody>{rows}</tbody>
        </table>
      </body>
    </html>
    """
    return HTMLResponse(body)


@router.get("/admin/stacks/latest.wav", include_in_schema=False)
def download_latest_stack(
    request: Request,
    _: HTTPBasicCredentials = Depends(_admin_credentials),
) -> FileResponse:
    paths = ProjectPaths(request.app.state.root)
    latest = StackHistoryStore(paths.public_history_file).latest()
    if latest is None:
        raise HTTPException(status_code=404, detail="stack history is empty")
    return _stack_file_response(paths, latest)


@router.get("/admin/stacks/{version_id}.wav", include_in_schema=False)
def download_stack_version(
    version_id: str,
    request: Request,
    _: HTTPBasicCredentials = Depends(_admin_credentials),
) -> FileResponse:
    paths = ProjectPaths(request.app.state.root)
    record = StackHistoryStore(paths.public_history_file).get(version_id)
    if record is None:
        raise HTTPException(status_code=404, detail="stack version not found")
    return _stack_file_response(paths, record)


def _admin_credentials(
    request: Request,
    credentials: HTTPBasicCredentials = Depends(security),
) -> HTTPBasicCredentials:
    settings: PublicRecorderSettings = request.app.state.public_settings
    username_ok = secrets.compare_digest(credentials.username, settings.admin_username)
    password_ok = secrets.compare_digest(credentials.password, settings.admin_password)
    if not (username_ok and password_ok):
        raise HTTPException(
            status_code=401,
            detail="incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials


def _record_row(record: StackHistoryRecord) -> str:
    filename = Path(record.stack_path).name
    return (
        "<tr>"
        f"<td>{html.escape(record.created_at)}</td>"
        f"<td>{html.escape(record.kind)}</td>"
        f"<td>{html.escape(filename)}</td>"
        f'<td><a href="/admin/stacks/{html.escape(record.id)}.wav">download</a></td>'
        "</tr>"
    )


def _stack_file_response(paths: ProjectPaths, record: StackHistoryRecord) -> FileResponse:
    stack_path = _safe_stack_path(paths, record.stack_path)
    if not stack_path.exists():
        raise HTTPException(status_code=404, detail="stack file is missing")
    return FileResponse(
        stack_path,
        media_type="audio/wav",
        filename=stack_path.name,
    )


def _safe_stack_path(paths: ProjectPaths, relative_path: str) -> Path:
    candidate = (paths.root / relative_path).resolve()
    stack_root = paths.voice_stack_sources_dir.resolve()
    if not candidate.is_relative_to(stack_root):
        raise HTTPException(status_code=409, detail="stack path is outside stack directory")
    return candidate
```

- [ ] **Step 4: Run admin tests**

Run:

```bash
uv run pytest tests/web/test_admin_stack_routes.py -q
```

Expected: passes.

- [ ] **Step 5: Commit**

```bash
git add src/secret_pond/web/admin_routes.py tests/web/test_admin_stack_routes.py
git commit -m "feat: add admin stack downloads"
```

## Task 6: Public App Factory, CLI, Seed Initialization, and Deployment

**Files:**
- Create: `src/secret_pond/public_app.py`
- Modify: `src/secret_pond/cli.py`
- Create: `Dockerfile.public-recorder`
- Create: `render.yaml`
- Test: `tests/web/test_public_app.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write public app tests**

Create `tests/web/test_public_app.py`:

```python
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from secret_pond.public_app import create_public_app
from secret_pond.services.public_settings import PublicRecorderSettings


def test_public_app_health_does_not_build_operator_runtime(tmp_path: Path) -> None:
    app = create_public_app(
        root=tmp_path,
        public_settings=PublicRecorderSettings(
            public_recording_token="record-token",
            admin_username="admin",
            admin_password="secret-password",
        ),
    )

    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert not hasattr(app.state, "runtime")
```

- [ ] **Step 2: Add CLI seed initialization test**

Append to `tests/test_cli.py`:

```python
def test_run_public_recorder_init_seed_writes_stack_settings_and_history(tmp_path: Path) -> None:
    from secret_pond.audio.buffers import AudioBuffer
    from secret_pond.audio.file_io import read_wav, write_wav_atomic
    from secret_pond.cli import run_public_recorder_init_seed
    from secret_pond.config import AppSettings, AudioFormatSettings, VoiceStackSettings
    from secret_pond.paths import ProjectPaths
    from secret_pond.services.public_stack_history import StackHistoryStore
    from secret_pond.services.settings_store import SettingsState, SettingsStore

    paths = ProjectPaths(tmp_path)
    settings = AppSettings(
        audio=AudioFormatSettings(sample_rate=8_000, channels=2, loop_seconds=1),
        voice_stack=VoiceStackSettings(mode="live_ephemeral", loop_seconds=1),
    )
    SettingsStore(paths).save(SettingsState(active=settings, draft=settings))
    seed_path = tmp_path / "initial-stack.wav"
    write_wav_atomic(
        seed_path,
        AudioBuffer(samples=np.ones((4_000, 1), dtype=np.float32) * 0.03, sample_rate=8_000),
    )

    exit_code = run_public_recorder_init_seed(tmp_path, seed_path)

    stored = SettingsStore(paths).load()
    history = StackHistoryStore(paths.public_history_file).list_versions()
    assert exit_code == 0
    assert stored.active.sources.voice_stack_path == "data/sources/voice/stack/VS000000_seed.wav"
    assert stored.draft.sources.voice_stack_path == "data/sources/voice/stack/VS000000_seed.wav"
    assert (paths.voice_stack_sources_dir / "VS000000_seed.wav").exists()
    assert paths.voice_stack_raw.exists()
    assert read_wav(paths.voice_stack_raw).frames == 8_000
    assert len(history) == 1
    assert history[0].kind == "seed"
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/web/test_public_app.py tests/test_cli.py::test_run_public_recorder_init_seed_writes_stack_settings_and_history -q
```

Expected: fails because `public_app.py`, `PublicRecorderSettings`, and `run_public_recorder_init_seed` do not exist.

- [ ] **Step 4: Implement public app factory**

Create `src/secret_pond/public_app.py`:

```python
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from secret_pond.paths import ProjectPaths
from secret_pond.services.public_settings import PublicRecorderSettings
from secret_pond.web.admin_routes import router as admin_router
from secret_pond.web.public_routes import router as public_router

STATIC_DIR = Path(__file__).resolve().parent / "web" / "static"


def create_public_app(
    *,
    root: Path | None = None,
    public_settings: PublicRecorderSettings | None = None,
) -> FastAPI:
    app = FastAPI(title="The Secret Pond Public Voice Stack Recorder")
    app.state.root = root or Path.cwd()
    app.state.public_settings = public_settings or PublicRecorderSettings.from_env()
    ProjectPaths(app.state.root).ensure_directories()

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/health")
    def health() -> dict[str, bool]:
        return {"ok": True}

    app.include_router(public_router)
    app.include_router(admin_router)
    return app
```

- [ ] **Step 5: Add CLI commands**

Modify `src/secret_pond/cli.py`:

```python
    public_serve_parser = subparsers.add_parser(
        "public-recorder-serve",
        help="Run the public Voice Stack recorder web server.",
    )
    public_serve_parser.add_argument("--root", type=Path, default=Path.cwd())
    public_serve_parser.add_argument("--host", default="0.0.0.0")
    public_serve_parser.add_argument("--port", type=int, default=8000)

    seed_parser = subparsers.add_parser(
        "public-recorder-init-seed",
        help="Install the initial public Voice Stack seed into data/.",
    )
    seed_parser.add_argument("--root", type=Path, default=Path.cwd())
    seed_parser.add_argument("--seed", type=Path, required=True)
```

Add command dispatch:

```python
    if args.command == "public-recorder-serve":
        return run_public_recorder_serve(args.root, args.host, args.port)
    if args.command == "public-recorder-init-seed":
        return run_public_recorder_init_seed(args.root, args.seed)
```

Add functions:

```python
def run_public_recorder_serve(root: Path, host: str, port: int) -> int:
    import uvicorn
    from secret_pond.public_app import create_public_app

    uvicorn.run(create_public_app(root=root), host=host, port=port)
    return 0
```

Add seed initialization to `src/secret_pond/services/public_voice_stack.py`:

```python
def initialize_seed_stack(
    *,
    paths: ProjectPaths,
    settings_store: SettingsStore,
    history_store: StackHistoryStore,
    seed_path: Path,
) -> StackHistoryRecord:
    if history_store.latest() is not None:
        msg = "public stack history is already initialized"
        raise ValueError(msg)
    current = settings_store.load()
    active = _public_active_settings(current.active)
    target_frames = active.audio.sample_rate * active.voice_stack.loop_seconds
    seed = read_wav(seed_path).to_canonical(
        sample_rate=active.audio.sample_rate,
        channels=active.audio.channels,
    )
    seed = seed.to_frame_count(target_frames)
    relative_stack_path = "data/sources/voice/stack/VS000000_seed.wav"
    absolute_stack_path = paths.root / relative_stack_path
    write_wav_atomic(absolute_stack_path, seed)
    write_wav_atomic(paths.voice_stack_raw, seed)
    active.sources.voice_raw_path = None
    active.sources.voice_stack_path = relative_stack_path
    draft = current.draft.model_copy(
        update={
            "voice_stack": active.voice_stack,
            "sources": current.draft.sources.model_copy(
                update={"voice_raw_path": None, "voice_stack_path": relative_stack_path}
            ),
        },
        deep=True,
    )
    settings_store.save(SettingsState(active=active, draft=draft))
    return history_store.record_seed(
        stack_path=relative_stack_path,
        duration_seconds=seed.frames / seed.sample_rate if seed.sample_rate else 0.0,
        file_size=absolute_stack_path.stat().st_size,
        sha256=_sha256_file(absolute_stack_path),
    )
```

Add CLI function:

```python
def run_public_recorder_init_seed(root: Path, seed: Path) -> int:
    from secret_pond.services.public_stack_history import StackHistoryStore
    from secret_pond.services.public_voice_stack import initialize_seed_stack

    paths = ProjectPaths(root)
    paths.ensure_directories()
    settings_store = SettingsStore(paths)
    settings_store.load_for_startup()
    record = initialize_seed_stack(
        paths=paths,
        settings_store=settings_store,
        history_store=StackHistoryStore(paths.public_history_file),
        seed_path=seed,
    )
    print(f"Initialized public Voice Stack seed: {record.stack_path}")
    return 0
```

- [ ] **Step 6: Create Dockerfile**

Create `Dockerfile.public-recorder`:

```dockerfile
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV SECRET_POND_ROOT=/app

WORKDIR /srv/secret-pond

RUN apt-get update \
  && apt-get install -y --no-install-recommends ffmpeg libsndfile1 portaudio19-dev \
  && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir .

EXPOSE 8000

CMD ["sh", "-c", "secret-pond public-recorder-serve --root ${SECRET_POND_ROOT:-/app} --host 0.0.0.0 --port ${PORT:-8000}"]
```

- [ ] **Step 7: Create Render blueprint**

Create `render.yaml`:

```yaml
services:
  - type: web
    name: secret-pond-public-recorder
    env: docker
    plan: starter
    dockerfilePath: ./Dockerfile.public-recorder
    disk:
      name: secret-pond-public-data
      mountPath: /app/data
      sizeGB: 1
    envVars:
      - key: SECRET_POND_ROOT
        value: /app
      - key: PUBLIC_RECORDING_TOKEN
        sync: false
      - key: ADMIN_USERNAME
        value: admin
      - key: ADMIN_PASSWORD
        sync: false
      - key: PUBLIC_MAX_UPLOAD_BYTES
        value: "26214400"
      - key: PUBLIC_STACK_LOCK_TIMEOUT_SECONDS
        value: "60"
```

- [ ] **Step 8: Run app and CLI tests**

Run:

```bash
uv run pytest tests/web/test_public_app.py tests/web/test_public_recorder_routes.py tests/web/test_admin_stack_routes.py tests/services/test_public_voice_stack.py tests/services/test_public_stack_history.py -q
```

Expected: passes.

- [ ] **Step 9: Build Docker image locally**

Run:

```bash
docker build -f Dockerfile.public-recorder -t secret-pond-public-recorder .
```

Expected: image builds successfully.

- [ ] **Step 10: Commit**

```bash
git add src/secret_pond/public_app.py src/secret_pond/cli.py Dockerfile.public-recorder render.yaml tests/web/test_public_app.py tests/test_cli.py
git commit -m "feat: add public recorder deployment"
```

## Task 7: Operator Documentation and Release Verification

**Files:**
- Create: `docs/operator-public-recorder.md`
- Modify: `README.md`

- [ ] **Step 1: Create operator guide**

Create `docs/operator-public-recorder.md`:

```markdown
# Public Voice Stack Recorder Operator Guide

## Purpose

This short-lived deployment lets invited users record from a mobile web link and add their take to the latest Voice Stack. It does not expose the full operator dashboard.

## User Privacy Contract

The public recorder stores only accumulated Voice Stack WAV versions and stack metadata. Individual uploaded voice files are used as temporary processing input, then deleted on success or failure. Public submissions do not create Voice Raw files under `data/sources/voice/raw/` and do not create accepted clips under `data/processed/accepted/`.

## Required Environment Variables

```text
PUBLIC_RECORDING_TOKEN=<long random token>
ADMIN_USERNAME=admin
ADMIN_PASSWORD=<long random password>
PUBLIC_MAX_UPLOAD_BYTES=26214400
PUBLIC_STACK_LOCK_TIMEOUT_SECONDS=60
SECRET_POND_ROOT=/app
```

## Render Setup

1. Create a Render Web Service from the GitHub repository.
2. Use `Dockerfile.public-recorder`.
3. Attach a 1 GB persistent disk at `/app/data`.
4. Set the required environment variables.
5. Deploy one instance with one worker.

## Initial Stack Setup

After deployment, open a Render shell and run:

```bash
secret-pond public-recorder-init-seed --root /app --seed /tmp/initial-stack.wav
```

Confirm:

```bash
ls -lh /app/data/sources/voice/stack
ls -lh /app/data/voice/voice_stack_raw.wav
```

## Public Link

Share only this link:

```text
https://<render-service-host>/r/<PUBLIC_RECORDING_TOKEN>
```

## Admin Download

Open:

```text
https://<render-service-host>/admin
```

Use `ADMIN_USERNAME` and `ADMIN_PASSWORD`. Download `Latest stack` during or after the collection period. Historical stack versions stay listed.

## End of Collection

1. Download latest stack and any historical versions needed.
2. Verify downloaded WAV files locally.
3. Stop the Render service.
4. Keep or delete the Render disk after confirming backups.
```

- [ ] **Step 2: Add README pointer**

Add to `README.md` near the web server section:

```markdown
For the short-lived online Voice Stack collection server, use
`docs/operator-public-recorder.md`. That deployment exposes only the public
mobile recorder and password-protected stack downloads; it does not expose the
local operator dashboard.
```

- [ ] **Step 3: Run documentation and focused tests**

Run:

```bash
uv run pytest tests/services/test_public_settings.py tests/services/test_public_stack_history.py tests/services/test_public_voice_stack.py tests/web/test_public_app.py tests/web/test_public_recorder_routes.py tests/web/test_admin_stack_routes.py -q
```

Expected: passes.

Run:

```bash
uv run ruff check src/secret_pond/services/public_settings.py src/secret_pond/services/public_stack_history.py src/secret_pond/services/public_voice_stack.py src/secret_pond/web/public_routes.py src/secret_pond/web/admin_routes.py src/secret_pond/public_app.py
```

Expected: passes.

- [ ] **Step 4: Commit**

```bash
git add docs/operator-public-recorder.md README.md
git commit -m "docs: add public recorder operator guide"
```

## Verification Matrix

| Requirement | Evidence after implementation |
| --- | --- |
| Mobile public recording link exists | `GET /r/{PUBLIC_RECORDING_TOKEN}` returns `public_recorder.html`; wrong token returns 404 |
| Browser recording uses standard APIs | `public_recorder.js` calls `navigator.mediaDevices.getUserMedia` and `MediaRecorder` |
| No post-add cancellation | UI has `Retry` before submit and no rollback/delete endpoint after submit |
| Individual voice files are not retained | Public route/service tests assert empty `data/sources/voice/raw/`, empty `data/processed/accepted/`, and empty temp upload glob after request |
| Adds to latest stack after waiting | Service tests assert a held lock times out and two accepted commits form a parent chain from first to second |
| Stack history is preserved | SQLite tests and admin page tests list all history rows |
| Admin downloads latest and historical stacks | `GET /admin/stacks/latest.wav` and `/admin/stacks/{version_id}.wav` return `audio/wav` under Basic Auth |
| Public app does not expose local dashboard | `create_public_app` does not include the operator `api_router` or websocket router |
| Render keeps data | `render.yaml` defines a persistent disk mounted at `/app/data` |
| Initial stack can be seeded | CLI test verifies `public-recorder-init-seed` writes `VS000000_seed.wav`, `voice_stack_raw.wav`, settings, and history |

## Manual Release Checklist

- [ ] Generate a long random `PUBLIC_RECORDING_TOKEN`.
- [ ] Generate a long random `ADMIN_PASSWORD`.
- [ ] Deploy Render Starter Web Service with a 1 GB disk mounted at `/app/data`.
- [ ] Seed the initial stack with `secret-pond public-recorder-init-seed --root /app --seed /tmp/initial-stack.wav`.
- [ ] Open `https://<host>/health` and confirm `{"ok": true}`.
- [ ] Open `/r/<token>` on iPhone Safari and Android Chrome if available.
- [ ] Submit one test recording.
- [ ] Confirm `/admin` lists the new stack version.
- [ ] Download latest stack and verify it opens locally.
- [ ] Confirm Render shell has no `public-upload-*` files under `/app/data/recordings_temp`.
- [ ] Stop or delete the service after the 3 to 5 day collection period and after downloads are verified.

## Plan Self-Review

- Spec coverage: The plan covers the public token link, mobile browser recording, pre-add discard, no post-add rollback, temporary raw deletion, latest-stack locking, immutable stack history, admin password download, initial seed, Render deployment, and short-lived operating procedure.
- Placeholder scan: The plan does not rely on deferred fields or unspecified tasks. Every created module has named responsibilities, tests, and commands.
- Type consistency: The public service uses existing `ProjectPaths`, `SettingsStore`, `SettingsState`, `AppSettings`, `VoiceStackStore`, and `AudioBuffer` types. New public settings, history, and result dataclasses have stable names used consistently across tests and routes.
