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
    write_wav_atomic(path, AudioBuffer(samples=np.column_stack([tone, tone]), sample_rate=sample_rate))


def prepare_settings(root: Path) -> None:
    settings = app_settings()
    SettingsStore(ProjectPaths(root)).save(SettingsState(active=settings, draft=settings))


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
