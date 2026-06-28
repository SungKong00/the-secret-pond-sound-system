from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from filelock import FileLock, Timeout

from secret_pond.audio.effects import apply_recording_processing
from secret_pond.audio.file_io import read_wav
from secret_pond.audio.voice_stack import VoiceStackAddResult, VoiceStackStore
from secret_pond.config import AppSettings
from secret_pond.paths import ProjectPaths
from secret_pond.services.file_snapshots import FileSnapshot, capture_file_snapshot, restore_file_snapshot
from secret_pond.services.public_settings import PublicRecorderSettings
from secret_pond.services.public_stack_history import StackHistoryRecord, StackHistoryStore
from secret_pond.services.settings_store import SettingsState, SettingsStore


class PublicVoiceStackError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class PublicVoiceStackResult:
    history_record: StackHistoryRecord
    add_result: VoiceStackAddResult


@dataclass(frozen=True)
class _SideEffectSnapshot:
    settings: FileSnapshot
    voice_stack_raw: FileSnapshot
    voice_manifest: FileSnapshot
    stack_files: set[Path]


class PublicVoiceStackService:
    def __init__(self, paths: ProjectPaths, settings: PublicRecorderSettings) -> None:
        self._paths = paths
        self._settings = settings
        self._settings_store = SettingsStore(paths)
        self._voice_stack = VoiceStackStore(paths)
        self._history_store = StackHistoryStore(paths.public_history_file)

    def add_upload_file(self, upload_path: Path) -> PublicVoiceStackResult:
        wav_path: Path | None = None
        try:
            wav_path = self.decode_upload_to_wav(upload_path)
            return self.add_decoded_wav(wav_path)
        finally:
            if wav_path is not None and wav_path != upload_path:
                wav_path.unlink(missing_ok=True)
            upload_path.unlink(missing_ok=True)

    def decode_upload_to_wav(self, upload_path: Path) -> Path:
        if upload_path.suffix.lower() == ".wav":
            return upload_path

        self._paths.ensure_directories()
        wav_path = self._paths.recordings_temp_dir / f"public-upload-{uuid4().hex}.wav"
        command = [
            "ffmpeg",
            "-y",
            "-i",
            str(upload_path),
            "-acodec",
            "pcm_s16le",
            str(wav_path),
        ]
        subprocess.run(command, check=True, capture_output=True)
        return wav_path

    def add_decoded_wav(self, wav_path: Path) -> PublicVoiceStackResult:
        try:
            with FileLock(self._paths.public_stack_lock_file).acquire(
                timeout=self._settings.stack_lock_timeout_seconds
            ):
                return self._add_decoded_wav_locked(wav_path)
        except Timeout as exc:
            raise PublicVoiceStackError("lock_timeout") from exc

    def _add_decoded_wav_locked(self, wav_path: Path) -> PublicVoiceStackResult:
        self._paths.ensure_directories()
        state = self._settings_store.load()
        active = _public_active_settings(state.active)
        loaded = read_wav(wav_path)
        canonical = loaded.to_canonical(
            sample_rate=active.audio.sample_rate,
            channels=active.audio.channels,
        )
        duration_seconds = canonical.frames / canonical.sample_rate if canonical.sample_rate else 0.0
        if duration_seconds < self._settings.minimum_duration_seconds:
            raise PublicVoiceStackError("too_short")
        if duration_seconds > self._settings.maximum_duration_seconds:
            raise PublicVoiceStackError("too_long")

        snapshot = self._capture_snapshot()
        try:
            processed = apply_recording_processing(canonical, active.recording)
            add_result = self._voice_stack.add_processed_voice(
                processed,
                active,
                processing_settings_snapshot=active.recording.model_dump(mode="json"),
            )
            if add_result.voice_stack_path is None:
                raise PublicVoiceStackError("processing_failed")

            active.sources.voice_stack_path = add_result.voice_stack_path
            self._settings_store.save(SettingsState(active=active, draft=active))
            stack_path = self._paths.root / add_result.voice_stack_path
            record = self._history_store.record_commit(
                parent_version_id=None
                if self._history_store.latest() is None
                else self._history_store.latest().id,
                stack_path=add_result.voice_stack_path,
                duration_seconds=duration_seconds,
                file_size=stack_path.stat().st_size,
                sha256=_sha256(stack_path),
                added_chunks=add_result.added_chunks,
                peak_before_guard=add_result.peak_before_guard,
                peak_after_guard=add_result.peak_after_guard,
                gain_reduction_db=add_result.gain_reduction_db,
            )
        except Exception:
            self._restore_snapshot(snapshot)
            raise

        return PublicVoiceStackResult(history_record=record, add_result=add_result)

    def _capture_snapshot(self) -> _SideEffectSnapshot:
        return _SideEffectSnapshot(
            settings=capture_file_snapshot(self._paths.settings_file),
            voice_stack_raw=capture_file_snapshot(self._paths.voice_stack_raw),
            voice_manifest=capture_file_snapshot(self._paths.voice_manifest),
            stack_files=set(self._paths.voice_stack_sources_dir.glob("*.wav")),
        )

    def _restore_snapshot(self, snapshot: _SideEffectSnapshot) -> None:
        restore_file_snapshot(self._paths.settings_file, snapshot.settings)
        restore_file_snapshot(self._paths.voice_stack_raw, snapshot.voice_stack_raw)
        restore_file_snapshot(self._paths.voice_manifest, snapshot.voice_manifest)
        for path in self._paths.voice_stack_sources_dir.glob("*.wav"):
            if path not in snapshot.stack_files:
                path.unlink(missing_ok=True)


def _public_active_settings(settings: AppSettings) -> AppSettings:
    return settings.model_copy(
        update={
            "input_control": settings.input_control.model_copy(
                update={
                    "minimum_recording_seconds": 3.0,
                    "maximum_recording_seconds": 600.0,
                }
            ),
            "voice_stack": settings.voice_stack.model_copy(update={"mode": "live_ephemeral"}),
        },
        deep=True,
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
