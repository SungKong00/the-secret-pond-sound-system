from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from math import log10
from pathlib import Path
from uuid import uuid4

import numpy as np
from filelock import FileLock, Timeout

from secret_pond.audio.buffers import AudioBuffer
from secret_pond.audio.effects import apply_recording_processing
from secret_pond.audio.file_io import read_wav
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
from secret_pond.services.settings_store import SettingsState, SettingsStore

_EDGE_TRIM_FRAME_MS = 20.0
_EDGE_TRIM_PADDING_MS = 250.0
_EDGE_TRIM_ABSOLUTE_FLOOR = 0.0015
_EDGE_TRIM_RELATIVE_PEAK = 0.03
_EDGE_TRIM_MIN_RETAIN_SECONDS = 0.5


class PublicVoiceStackError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class PublicVoiceStackResult:
    history_record: StackHistoryRecord
    add_result: VoiceStackAddResult


@dataclass(frozen=True)
class _LevelGuardResult:
    buffer: AudioBuffer
    rms_dbfs: float
    gain_db: float
    peak_after: float


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
        try:
            subprocess.run(command, check=True, capture_output=True)
        except (FileNotFoundError, subprocess.CalledProcessError) as exc:
            wav_path.unlink(missing_ok=True)
            raise PublicVoiceStackError("decode_failed") from exc
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
        parent_record = self._history_store.latest()
        if parent_record is not None:
            active.sources.voice_stack_path = parent_record.stack_path
        loaded = read_wav(wav_path)
        canonical = loaded.to_canonical(
            sample_rate=active.audio.sample_rate,
            channels=active.audio.channels,
        )
        duration_seconds = (
            canonical.frames / canonical.sample_rate if canonical.sample_rate else 0.0
        )
        if duration_seconds < self._settings.minimum_duration_seconds:
            raise PublicVoiceStackError("too_short")
        if duration_seconds > self._settings.maximum_duration_seconds:
            raise PublicVoiceStackError("too_long")

        snapshot = self._capture_snapshot()
        try:
            if parent_record is None:
                _reset_empty_public_stack_base(self._paths, active)
            trimmed = _trim_edge_waiting(canonical)
            processed = apply_recording_processing(trimmed, active.recording)
            level_guard = _apply_public_level_guard(processed, self._settings)
            add_result = self._voice_stack.add_processed_voice(
                level_guard.buffer,
                active,
                processing_settings_snapshot=active.recording.model_dump(mode="json"),
            )
            if add_result.voice_stack_path is None:
                raise PublicVoiceStackError("processing_failed")

            active.sources.voice_stack_path = add_result.voice_stack_path
            self._settings_store.save(SettingsState(active=active, draft=active))
            stack_path = self._paths.root / add_result.voice_stack_path
            record = self._history_store.record_commit(
                parent_version_id=None if parent_record is None else parent_record.id,
                stack_path=add_result.voice_stack_path,
                duration_seconds=duration_seconds,
                file_size=stack_path.stat().st_size,
                sha256=_sha256(stack_path),
                added_chunks=add_result.added_chunks,
                peak_before_guard=add_result.peak_before_guard,
                peak_after_guard=add_result.peak_after_guard,
                gain_reduction_db=add_result.gain_reduction_db,
                level_guard_rms_dbfs=level_guard.rms_dbfs,
                level_guard_gain_db=level_guard.gain_db,
                level_guard_peak_after=level_guard.peak_after,
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


def _reset_empty_public_stack_base(paths: ProjectPaths, settings: AppSettings) -> None:
    settings.sources.voice_stack_path = None
    paths.voice_stack_raw.unlink(missing_ok=True)
    paths.voice_manifest.unlink(missing_ok=True)


def _trim_edge_waiting(buffer: AudioBuffer) -> AudioBuffer:
    samples = buffer.samples
    if samples.shape[0] == 0:
        return buffer

    peak = _peak(samples)
    if peak <= 0.0:
        return buffer

    frame_size = max(1, int(round(buffer.sample_rate * (_EDGE_TRIM_FRAME_MS / 1000.0))))
    threshold = max(_EDGE_TRIM_ABSOLUTE_FLOOR, peak * _EDGE_TRIM_RELATIVE_PEAK)
    active_windows: list[int] = []
    for window_index, start in enumerate(range(0, samples.shape[0], frame_size)):
        window = samples[start : start + frame_size]
        if _rms(window) >= threshold:
            active_windows.append(window_index)

    if not active_windows:
        return buffer

    padding = int(round(buffer.sample_rate * (_EDGE_TRIM_PADDING_MS / 1000.0)))
    start_frame = max(0, active_windows[0] * frame_size - padding)
    end_frame = min(samples.shape[0], (active_windows[-1] + 1) * frame_size + padding)
    min_retain_frames = min(
        samples.shape[0],
        int(round(buffer.sample_rate * _EDGE_TRIM_MIN_RETAIN_SECONDS)),
    )
    if end_frame - start_frame < min_retain_frames:
        return buffer
    if start_frame == 0 and end_frame == samples.shape[0]:
        return buffer

    return AudioBuffer(
        samples=samples[start_frame:end_frame].copy(),
        sample_rate=buffer.sample_rate,
    )


def _apply_public_level_guard(
    buffer: AudioBuffer,
    settings: PublicRecorderSettings,
) -> _LevelGuardResult:
    rms_dbfs = _rms_dbfs(buffer.samples)
    gain_db = _coarse_level_gain_db(rms_dbfs, settings)
    guarded = _apply_gain_db(buffer.samples, gain_db)
    peak_after = _peak(guarded)
    if peak_after > settings.level_guard_peak_ceiling:
        peak_gain_db = 20.0 * log10(settings.level_guard_peak_ceiling / peak_after)
        guarded = _apply_gain_db(guarded, peak_gain_db)
        gain_db += peak_gain_db
        peak_after = _peak(guarded)
    return _LevelGuardResult(
        buffer=AudioBuffer(samples=guarded, sample_rate=buffer.sample_rate),
        rms_dbfs=rms_dbfs,
        gain_db=gain_db,
        peak_after=peak_after,
    )


def _coarse_level_gain_db(rms_dbfs: float, settings: PublicRecorderSettings) -> float:
    if rms_dbfs < settings.level_guard_quiet_rms_dbfs:
        return min(
            settings.level_guard_quiet_target_dbfs - rms_dbfs,
            settings.level_guard_max_boost_db,
        )
    if rms_dbfs > settings.level_guard_loud_rms_dbfs:
        return settings.level_guard_loud_target_dbfs - rms_dbfs
    return 0.0


def _apply_gain_db(samples: np.ndarray, gain_db: float) -> np.ndarray:
    if gain_db == 0.0:
        return samples.astype(np.float32, copy=True)
    return (samples.astype(np.float32, copy=True) * (10.0 ** (gain_db / 20.0))).astype(
        np.float32
    )


def _rms_dbfs(samples: np.ndarray) -> float:
    if samples.shape[0] == 0:
        return -120.0
    rms = _rms(samples)
    if rms <= 0.0 or not np.isfinite(rms):
        return -120.0
    return 20.0 * log10(rms)


def _rms(samples: np.ndarray) -> float:
    if samples.shape[0] == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(samples.astype(np.float32, copy=False)))))


def _peak(samples: np.ndarray) -> float:
    if samples.shape[0] == 0:
        return 0.0
    return float(np.max(np.abs(samples)))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
