from __future__ import annotations

from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient

from secret_pond.audio.buffers import AudioBuffer
from secret_pond.audio.file_io import write_wav_atomic
from secret_pond.config import (
    AppSettings,
    AudioFormatSettings,
    InputControlSettings,
    RecordingProcessingSettings,
    VoiceStackSettings,
)
from secret_pond.paths import ProjectPaths
from secret_pond.public_app import create_public_app
from secret_pond.services.public_settings import PublicRecorderSettings
from secret_pond.services.public_stack_history import StackHistoryRecord, StackHistoryStore
from secret_pond.services.settings_store import SettingsState, SettingsStore


def app_settings() -> AppSettings:
    return AppSettings(
        audio=AudioFormatSettings(sample_rate=8_000, channels=2, loop_seconds=1),
        input_control=InputControlSettings(
            minimum_recording_seconds=3.0,
            maximum_recording_seconds=600.0,
        ),
        recording=RecordingProcessingSettings(
            gain_db=0.0,
            normalize_peak=0.2,
            highpass_hz=90.0,
            lowpass_hz=3_000.0,
            presence_gain_db=0.0,
            reverb_mix=0.0,
            delay_mix=0.0,
            fade_ms=0,
        ),
        voice_stack=VoiceStackSettings(mode="live_ephemeral", loop_seconds=1, insert_gain_db=0.0),
    )


def write_take(path: Path, *, seconds: float = 3.0) -> None:
    sample_rate = 8_000
    frames = int(sample_rate * seconds)
    t = np.arange(frames, dtype=np.float32) / sample_rate
    tone = np.sin(2 * np.pi * 440.0 * t).astype(np.float32) * 0.04
    write_wav_atomic(
        path,
        AudioBuffer(samples=np.column_stack([tone, tone]), sample_rate=sample_rate),
    )


def prepare_settings(root: Path) -> None:
    settings = app_settings()
    SettingsStore(ProjectPaths(root)).save(SettingsState(active=settings, draft=settings))


def prepare_stack_history(root: Path) -> tuple[StackHistoryRecord, StackHistoryRecord]:
    paths = ProjectPaths(root)
    paths.ensure_directories()
    seed_path = paths.voice_stack_sources_dir / "seed.wav"
    commit_path = paths.voice_stack_sources_dir / "commit.wav"
    seed_path.write_bytes(b"seed-stack")
    commit_path.write_bytes(b"commit-stack")
    store = StackHistoryStore(paths.public_history_file)
    seed = store.record_seed(
        stack_path=str(seed_path.relative_to(root)),
        duration_seconds=10.0,
        file_size=seed_path.stat().st_size,
        sha256="a" * 64,
    )
    commit = store.record_commit(
        parent_version_id=seed.id,
        stack_path=str(commit_path.relative_to(root)),
        duration_seconds=13.0,
        file_size=commit_path.stat().st_size,
        sha256="b" * 64,
        added_chunks=1,
        peak_before_guard=0.2,
        peak_after_guard=0.2,
        gain_reduction_db=0.0,
    )
    return seed, commit


def test_public_recorder_renders_for_valid_token(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PUBLIC_RECORDING_TOKEN", "record-token")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "secret-password")

    client = TestClient(create_public_app(root=tmp_path))

    response = client.get("/r/record-token")

    assert response.status_code == 200
    assert "Voice Stack" in response.text
    assert "operator" not in response.text.lower()


def test_public_recorder_rejects_wrong_token(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PUBLIC_RECORDING_TOKEN", "record-token")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "secret-password")

    client = TestClient(create_public_app(root=tmp_path))

    response = client.get("/r/wrong-token")

    assert response.status_code == 404


def test_public_recording_upload_rejects_too_large_file(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("PUBLIC_RECORDING_TOKEN", "record-token")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "secret-password")
    monkeypatch.setenv("PUBLIC_MAX_UPLOAD_BYTES", "4")

    client = TestClient(create_public_app(root=tmp_path))

    response = client.post(
        "/api/public/recordings",
        headers={"X-Public-Recording-Token": "record-token"},
        files={"file": ("take.webm", b"12345", "audio/webm")},
    )

    assert response.status_code == 413
    assert response.json()["detail"] == "file_too_large"


def test_public_recording_upload_commits_stack_and_deletes_raw(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("PUBLIC_RECORDING_TOKEN", "record-token")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "secret-password")
    prepare_settings(tmp_path)
    upload = tmp_path / "take.wav"
    write_take(upload)
    client = TestClient(create_public_app(root=tmp_path))

    with upload.open("rb") as handle:
        response = client.post(
            "/api/public/recordings",
            headers={"X-Public-Recording-Token": "record-token"},
            files={"file": ("take.wav", handle, "audio/wav")},
        )

    paths = ProjectPaths(tmp_path)
    assert response.status_code == 201
    assert response.json()["stack_path"].startswith("data/sources/voice/stack/")
    assert list(paths.recordings_temp_dir.glob("public-upload-*")) == []
    assert list(paths.voice_raw_sources_dir.glob("*.wav")) == []
    assert list(paths.accepted_dir.glob("*.wav")) == []


def test_public_recording_upload_maps_too_short_to_specific_reason(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("PUBLIC_RECORDING_TOKEN", "record-token")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "secret-password")
    prepare_settings(tmp_path)
    upload = tmp_path / "short.wav"
    write_take(upload, seconds=1.0)
    client = TestClient(create_public_app(root=tmp_path))

    with upload.open("rb") as handle:
        response = client.post(
            "/api/public/recordings",
            headers={"X-Public-Recording-Token": "record-token"},
            files={"file": ("short.wav", handle, "audio/wav")},
        )

    assert response.status_code == 422
    assert response.json()["detail"] == "too_short"


def test_public_recording_upload_maps_too_long_to_specific_reason(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("PUBLIC_RECORDING_TOKEN", "record-token")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "secret-password")
    prepare_settings(tmp_path)
    upload = tmp_path / "too-long.wav"
    write_take(upload, seconds=4.0)
    client = TestClient(
        create_public_app(
            root=tmp_path,
            settings=PublicRecorderSettings(
                public_recording_token="record-token",
                admin_username="admin",
                admin_password="secret-password",
                maximum_duration_seconds=3.0,
            ),
        )
    )

    with upload.open("rb") as handle:
        response = client.post(
            "/api/public/recordings",
            headers={"X-Public-Recording-Token": "record-token"},
            files={"file": ("too-long.wav", handle, "audio/wav")},
        )

    assert response.status_code == 422
    assert response.json()["detail"] == "too_long"


def test_public_recording_upload_maps_processing_exception_and_cleans_temp_file(
    tmp_path: Path,
    monkeypatch,
) -> None:
    class BrokenPublicVoiceStackService:
        def __init__(self, *args, **kwargs):
            pass

        def add_upload_file(self, upload_path: Path):
            raise RuntimeError("processing unavailable")

    monkeypatch.setenv("PUBLIC_RECORDING_TOKEN", "record-token")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "secret-password")
    monkeypatch.setattr(
        "secret_pond.public_app.PublicVoiceStackService",
        BrokenPublicVoiceStackService,
    )
    client = TestClient(create_public_app(root=tmp_path), raise_server_exceptions=False)

    response = client.post(
        "/api/public/recordings",
        headers={"X-Public-Recording-Token": "record-token"},
        files={"file": ("take.wav", b"not used", "audio/wav")},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "processing_failed"
    assert list(ProjectPaths(tmp_path).recordings_temp_dir.glob("public-upload-*")) == []


def test_admin_version_list_requires_basic_auth(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PUBLIC_RECORDING_TOKEN", "record-token")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "secret-password")
    prepare_stack_history(tmp_path)
    client = TestClient(create_public_app(root=tmp_path))

    missing = client.get("/admin/versions")
    wrong = client.get("/admin/versions", auth=("admin", "wrong-password"))

    assert missing.status_code == 401
    assert missing.headers["www-authenticate"] == "Basic"
    assert wrong.status_code == 401


def test_admin_version_list_returns_seed_and_commit_versions(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("PUBLIC_RECORDING_TOKEN", "record-token")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "secret-password")
    seed, commit = prepare_stack_history(tmp_path)
    client = TestClient(create_public_app(root=tmp_path))

    response = client.get("/admin/versions", auth=("admin", "secret-password"))

    assert response.status_code == 200
    versions = response.json()["versions"]
    assert [version["id"] for version in versions] == [commit.id, seed.id]
    assert versions[0]["parent_version_id"] == seed.id
    assert versions[0]["kind"] == "commit"
    assert versions[1]["kind"] == "seed"


def test_admin_can_download_latest_and_historical_stack_versions(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("PUBLIC_RECORDING_TOKEN", "record-token")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "secret-password")
    seed, commit = prepare_stack_history(tmp_path)
    client = TestClient(create_public_app(root=tmp_path))

    latest = client.get("/admin/versions/latest/download", auth=("admin", "secret-password"))
    seed_download = client.get(
        f"/admin/versions/{seed.id}/download",
        auth=("admin", "secret-password"),
    )
    commit_download = client.get(
        f"/admin/versions/{commit.id}/download",
        auth=("admin", "secret-password"),
    )

    assert latest.status_code == 200
    assert latest.content == b"commit-stack"
    assert seed_download.status_code == 200
    assert seed_download.content == b"seed-stack"
    assert commit_download.status_code == 200
    assert commit_download.content == b"commit-stack"
