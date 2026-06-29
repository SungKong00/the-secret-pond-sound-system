from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
import pytest
from filelock import FileLock

from secret_pond.audio.buffers import AudioBuffer
from secret_pond.audio.file_io import read_wav, write_wav_atomic
from secret_pond.audio.voice_stack import VoiceStackStore
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
from secret_pond.services.public_voice_stack import (
    PublicVoiceStackError,
    PublicVoiceStackService,
)
from secret_pond.services.settings_store import SettingsState, SettingsStore


def public_settings(**overrides) -> PublicRecorderSettings:
    base = {
        "public_recording_token": "record-token",
        "admin_username": "admin",
        "admin_password": "secret-password",
        "max_upload_bytes": 25 * 1024 * 1024,
        "stack_lock_timeout_seconds": 1.0,
    }
    return PublicRecorderSettings(**{**base, **overrides})


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


def write_take(path: Path, *, seconds: float = 3.0, amplitude: float = 0.04) -> None:
    sample_rate = 8_000
    frames = int(sample_rate * seconds)
    t = np.arange(frames, dtype=np.float32) / sample_rate
    tone = np.sin(2 * np.pi * 440.0 * t).astype(np.float32) * amplitude
    write_wav_atomic(
        path,
        AudioBuffer(samples=np.column_stack([tone, tone]), sample_rate=sample_rate),
    )


def service(tmp_path: Path, **settings_overrides) -> PublicVoiceStackService:
    paths = ProjectPaths(tmp_path)
    SettingsStore(paths).save(SettingsState(active=app_settings(), draft=app_settings()))
    return PublicVoiceStackService(paths, public_settings(**settings_overrides))


def test_public_recording_adds_latest_stack_without_voice_raw(tmp_path: Path) -> None:
    upload = tmp_path / "upload.wav"
    write_take(upload)

    result = service(tmp_path).add_decoded_wav(upload)
    paths = ProjectPaths(tmp_path)
    records = StackHistoryStore(paths.public_history_file).list_versions()
    stored = SettingsStore(paths).load()

    assert result.history_record.stack_path.startswith("data/sources/voice/stack/")
    assert (tmp_path / result.history_record.stack_path).exists()
    assert paths.voice_stack_raw.exists()
    assert records[0] == result.history_record
    assert stored.active.sources.voice_stack_path == result.history_record.stack_path
    assert read_wav(paths.voice_stack_raw).frames == 8_000
    assert list(paths.voice_raw_sources_dir.glob("*.wav")) == []
    assert list(paths.accepted_dir.glob("*.wav")) == []


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


def test_public_recording_commit_uses_latest_non_deleted_version_as_parent(
    tmp_path: Path,
    monkeypatch,
) -> None:
    first_upload = tmp_path / "first.wav"
    second_upload = tmp_path / "second.wav"
    third_upload = tmp_path / "third.wav"
    write_take(first_upload, amplitude=0.04)
    write_take(second_upload, amplitude=0.06)
    write_take(third_upload, amplitude=0.05)
    stack_service = service(tmp_path)
    history = StackHistoryStore(ProjectPaths(tmp_path).public_history_file)

    first = stack_service.add_decoded_wav(first_upload)
    second = stack_service.add_decoded_wav(second_upload)
    history.mark_deleted(second.history_record.id)
    observed_stack_paths: list[str | None] = []
    original_add_processed_voice = VoiceStackStore.add_processed_voice

    def capture_add_processed_voice(self, buffer, settings, **kwargs):
        observed_stack_paths.append(settings.sources.voice_stack_path)
        return original_add_processed_voice(self, buffer, settings, **kwargs)

    monkeypatch.setattr(VoiceStackStore, "add_processed_voice", capture_add_processed_voice)
    third = stack_service.add_decoded_wav(third_upload)

    stored = SettingsStore(ProjectPaths(tmp_path)).load()
    assert observed_stack_paths == [first.history_record.stack_path]
    assert third.history_record.parent_version_id == first.history_record.id
    assert stored.active.sources.voice_stack_path == third.history_record.stack_path


def test_public_recording_deletes_upload_file_when_processing_fails(tmp_path: Path) -> None:
    upload = tmp_path / "too-short.wav"
    write_take(upload, seconds=1.0)

    with pytest.raises(PublicVoiceStackError, match="too_short"):
        service(tmp_path).add_upload_file(upload)

    assert not upload.exists()
    assert list(ProjectPaths(tmp_path).recordings_temp_dir.glob("public-upload-*")) == []


def test_public_recording_rejects_too_long_take(tmp_path: Path) -> None:
    upload = tmp_path / "too-long.wav"
    write_take(upload, seconds=4.0)

    with pytest.raises(PublicVoiceStackError, match="too_long"):
        service(tmp_path, maximum_duration_seconds=3.0).add_decoded_wav(upload)


def test_public_recording_maps_ffmpeg_decode_error_and_cleans_temp_files(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = ProjectPaths(tmp_path)
    paths.ensure_directories()
    upload = paths.recordings_temp_dir / "public-upload-bad.webm"
    upload.write_bytes(b"not audio")

    def fail_ffmpeg(command, **kwargs):
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr("secret_pond.services.public_voice_stack.subprocess.run", fail_ffmpeg)

    with pytest.raises(PublicVoiceStackError, match="decode_failed"):
        service(tmp_path).add_upload_file(upload)

    assert not upload.exists()
    assert list(paths.recordings_temp_dir.glob("public-upload-*")) == []


def test_public_recording_times_out_when_stack_lock_is_held(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path)
    paths.ensure_directories()
    upload = tmp_path / "upload.wav"
    write_take(upload)

    lock = FileLock(paths.public_stack_lock_file)
    lock.acquire(timeout=0)
    try:
        with pytest.raises(PublicVoiceStackError, match="lock_timeout"):
            service(tmp_path, stack_lock_timeout_seconds=0.01).add_decoded_wav(upload)
    finally:
        lock.release()


def test_public_recording_restores_stack_when_history_write_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    class BrokenHistoryStore(StackHistoryStore):
        def record_commit(self, **kwargs):
            raise RuntimeError("history unavailable")

    upload = tmp_path / "upload.wav"
    write_take(upload)
    paths = ProjectPaths(tmp_path)

    monkeypatch.setattr(
        "secret_pond.services.public_voice_stack.StackHistoryStore",
        BrokenHistoryStore,
    )

    with pytest.raises(RuntimeError, match="history unavailable"):
        service(tmp_path).add_decoded_wav(upload)

    stored = SettingsStore(paths).load()
    assert stored.active.sources.voice_stack_path is None
    assert not paths.voice_stack_raw.exists()
    assert list(paths.voice_stack_sources_dir.glob("*.wav")) == []
