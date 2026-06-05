from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from math import log10
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np
from pydantic import BaseModel

from secret_pond.audio.buffers import AudioBuffer
from secret_pond.audio.file_io import read_wav, write_wav_atomic
from secret_pond.audio.source_library import selected_source_path
from secret_pond.audio.voice_stack_naming import next_voice_stack_path
from secret_pond.config import AppSettings
from secret_pond.paths import ProjectPaths

_PEAK_CEILING = 0.98


@dataclass(frozen=True)
class VoiceStackSnapshot:
    buffer: AudioBuffer
    raw_created: bool
    raw_normalized: bool
    manifest_created: bool
    voice_stack_path: str | None = None


@dataclass(frozen=True)
class VoiceStackAddResult:
    added_chunks: int
    entries: list[dict[str, Any]]
    peak_before_guard: float
    peak_after_guard: float
    gain_reduction_db: float
    voice_stack_path: str | None = None
    voice_raw_path: str | None = None


@dataclass(frozen=True)
class VoiceStackRebuildResult:
    added_chunks: int
    entries: list[dict[str, Any]]
    peak_before_guard: float
    peak_after_guard: float
    gain_reduction_db: float
    voice_stack_path: str | None = None


@dataclass(frozen=True)
class VoiceStackSelectionState:
    selected_vr: str | None
    selected_vs: str | None


@dataclass(frozen=True)
class VoiceStackTransitionGuardState:
    playback_session_id: str | None
    current_stack_id: str


class VoiceStackStore:
    def __init__(self, paths: ProjectPaths) -> None:
        self._paths = paths
        self._playback_session_id: str | None = None

    def selected_voice_state(self, settings: AppSettings) -> VoiceStackSelectionState:
        return VoiceStackSelectionState(
            selected_vr=settings.sources.voice_raw_path,
            selected_vs=settings.sources.voice_stack_path,
        )

    def begin_playback_session(self) -> str:
        self._playback_session_id = uuid4().hex
        return self._playback_session_id

    def transition_guard_state(self, settings: AppSettings) -> VoiceStackTransitionGuardState:
        return VoiceStackTransitionGuardState(
            playback_session_id=self._playback_session_id,
            current_stack_id=self.current_stack_id(settings),
        )

    def current_stack_id(self, settings: AppSettings) -> str:
        return settings.sources.voice_stack_path or _relative_path(
            self._paths.root,
            self._paths.voice_stack_raw,
        )

    def ensure_initialized(self, settings: AppSettings) -> VoiceStackSnapshot:
        self._paths.ensure_directories()

        target_frames = settings.audio.sample_rate * settings.voice_stack.loop_seconds
        raw_created = False
        raw_normalized = False
        voice_stack_path: str | None = settings.sources.voice_stack_path
        current_stack_path = _current_stack_path(self._paths, settings)

        if current_stack_path.exists():
            loaded = read_wav(current_stack_path)
            buffer = loaded.to_canonical(
                sample_rate=settings.audio.sample_rate,
                channels=settings.audio.channels,
            )
            buffer = buffer.to_frame_count(target_frames)
            raw_normalized = not _matches_target(
                loaded,
                sample_rate=settings.audio.sample_rate,
                channels=settings.audio.channels,
                frames=target_frames,
            )
            if raw_normalized:
                voice_stack_path = _write_stack_buffer(
                    self._paths,
                    settings,
                    buffer,
                    timestamped=bool(settings.sources.voice_stack_path),
                )
        else:
            raw_created = True
            buffer = _silent_buffer(
                frames=target_frames,
                sample_rate=settings.audio.sample_rate,
                channels=settings.audio.channels,
            )
            voice_stack_path = _write_stack_buffer(
                self._paths,
                settings,
                buffer,
                timestamped=False,
            )

        manifest_created = self._ensure_manifest()
        return VoiceStackSnapshot(
            buffer=buffer,
            raw_created=raw_created,
            raw_normalized=raw_normalized,
            manifest_created=manifest_created,
            voice_stack_path=voice_stack_path,
        )

    def add_processed_voice(
        self,
        buffer: AudioBuffer,
        settings: AppSettings,
        processing_settings_snapshot: Mapping[str, Any] | BaseModel | None = None,
        offset_frames: int | None = None,
    ) -> VoiceStackAddResult:
        target_frames = settings.audio.sample_rate * settings.voice_stack.loop_seconds
        if offset_frames is not None and not 0 <= offset_frames < target_frames:
            msg = "offset_frames must be greater than or equal to 0 and less than the loop length"
            raise ValueError(msg)

        raw_existed_before_add = self._paths.voice_stack_raw.exists()
        previous_raw_bytes = (
            self._paths.voice_stack_raw.read_bytes() if raw_existed_before_add else None
        )
        snapshot = self.ensure_initialized(settings)
        manifest = _read_manifest(self._paths.voice_manifest)
        existing_entries = list(manifest.get("entries", []))
        current_revision = int(manifest.get("revision", 0))
        source = buffer.to_canonical(
            sample_rate=settings.audio.sample_rate,
            channels=settings.audio.channels,
        )
        chunks = _split_chunks(source, target_frames)
        if not chunks:
            peak = _peak(snapshot.buffer.samples)
            return VoiceStackAddResult(
                added_chunks=0,
                entries=[],
                peak_before_guard=peak,
                peak_after_guard=peak,
                gain_reduction_db=0.0,
            )

        stack_samples = snapshot.buffer.samples.astype(np.float32, copy=True)
        new_entries: list[dict[str, Any]] = []
        accepted_writes: list[tuple[Path, AudioBuffer]] = []
        snapshot_payload = _json_safe_snapshot(processing_settings_snapshot)
        for chunk_index, chunk in enumerate(chunks):
            entry_id = uuid4().hex
            chunk_offset = (
                offset_frames
                if offset_frames is not None
                else _deterministic_offset(
                    revision=current_revision,
                    existing_entry_count=len(existing_entries),
                    chunk_index=chunk_index,
                    loop_frames=target_frames,
                )
            )
            entry: dict[str, Any] = {
                "id": entry_id,
                "source_mode": settings.voice_stack.mode,
                "duration_seconds": chunk.original_frames / settings.audio.sample_rate,
                "offset_frames": chunk_offset,
                "gain_db": settings.voice_stack.insert_gain_db,
                "processing_settings_snapshot": snapshot_payload,
                "created_at": datetime.now(UTC).isoformat(),
                "source_sample_rate": buffer.sample_rate,
                "source_channels": buffer.channels,
            }
            if settings.voice_stack.mode == "test_library":
                relative_path = Path("data") / "processed" / "accepted" / f"{entry_id}.wav"
                entry["accepted_clip_path"] = relative_path.as_posix()
                accepted_writes.append((self._paths.root / relative_path, chunk.original_buffer))

            mixed_chunk = _apply_gain(
                chunk.loop_buffer.samples,
                settings.voice_stack.insert_gain_db,
            )
            _mix_wrapped(stack_samples, mixed_chunk, chunk_offset)
            new_entries.append(entry)

        peak_before_guard = _peak(stack_samples)
        guarded_samples, peak_after_guard, gain_reduction_db = _apply_peak_guard(stack_samples)
        raw_buffer = AudioBuffer(samples=guarded_samples, sample_rate=settings.audio.sample_rate)

        written_accepted_paths: list[Path] = []
        try:
            for path, accepted_buffer in accepted_writes:
                write_wav_atomic(path, accepted_buffer)
                written_accepted_paths.append(path)

            voice_stack_path = _write_stack_buffer(
                self._paths,
                settings,
                raw_buffer,
                timestamped=True,
            )
            manifest["revision"] = current_revision + 1
            manifest["entries"] = existing_entries + new_entries
            _write_json_atomic(self._paths.voice_manifest, manifest)
        except Exception:
            _cleanup_paths(written_accepted_paths)
            _restore_raw_stack(self._paths.voice_stack_raw, previous_raw_bytes)
            raise

        return VoiceStackAddResult(
            added_chunks=len(new_entries),
            entries=new_entries,
            peak_before_guard=peak_before_guard,
            peak_after_guard=peak_after_guard,
            gain_reduction_db=gain_reduction_db,
            voice_stack_path=voice_stack_path,
            voice_raw_path=None,
        )

    def rebuild_from_test_library(self, settings: AppSettings) -> VoiceStackRebuildResult:
        self._paths.ensure_directories()
        if not self._paths.voice_manifest.exists():
            msg = "voice stack manifest does not exist"
            raise ValueError(msg)

        target_frames = settings.audio.sample_rate * settings.voice_stack.loop_seconds
        manifest = _read_manifest(self._paths.voice_manifest)
        test_entries = _test_library_entries(manifest)
        if not test_entries:
            msg = "test_library manifest has no accepted clips to rebuild"
            raise ValueError(msg)
        stack_samples = np.zeros(
            (target_frames, settings.audio.channels),
            dtype=np.float32,
        )

        prepared: list[tuple[dict[str, Any], AudioBuffer]] = []
        for entry in test_entries:
            accepted_clip_path = entry.get("accepted_clip_path")
            if not accepted_clip_path:
                msg = "test_library manifest entry is missing accepted_clip_path"
                raise ValueError(msg)

            accepted_path = _accepted_clip_path(self._paths, str(accepted_clip_path))
            if not accepted_path.exists():
                msg = f"accepted clip does not exist: {accepted_clip_path}"
                raise ValueError(msg)

            accepted = read_wav(accepted_path).to_canonical(
                sample_rate=settings.audio.sample_rate,
                channels=settings.audio.channels,
            )
            prepared.append((entry, accepted.to_frame_count(target_frames)))

        for entry, accepted in prepared:
            offset_frames = _entry_offset(entry, target_frames)
            gain_db = float(entry.get("gain_db", 0.0))
            mixed_chunk = _apply_gain(accepted.samples, gain_db)
            _mix_wrapped(stack_samples, mixed_chunk, offset_frames)

        peak_before_guard = _peak(stack_samples)
        guarded_samples, peak_after_guard, gain_reduction_db = _apply_peak_guard(stack_samples)
        voice_stack_path = _write_stack_buffer(
            self._paths,
            settings,
            AudioBuffer(samples=guarded_samples, sample_rate=settings.audio.sample_rate),
            timestamped=True,
        )

        return VoiceStackRebuildResult(
            added_chunks=len(prepared),
            entries=test_entries,
            peak_before_guard=peak_before_guard,
            peak_after_guard=peak_after_guard,
            gain_reduction_db=gain_reduction_db,
            voice_stack_path=voice_stack_path,
        )

    def _ensure_manifest(self) -> bool:
        if self._paths.voice_manifest.exists():
            return False

        _write_json_atomic(
            self._paths.voice_manifest,
            {
                "schema_version": 1,
                "revision": 0,
                "entries": [],
            },
        )
        return True


@dataclass(frozen=True)
class _VoiceChunk:
    original_buffer: AudioBuffer
    loop_buffer: AudioBuffer
    original_frames: int


def _split_chunks(buffer: AudioBuffer, target_frames: int) -> list[_VoiceChunk]:
    chunks: list[_VoiceChunk] = []
    for start in range(0, buffer.frames, target_frames):
        samples = buffer.samples[start : start + target_frames]
        original = AudioBuffer(samples=samples, sample_rate=buffer.sample_rate)
        chunks.append(
            _VoiceChunk(
                original_buffer=original,
                loop_buffer=original.to_frame_count(target_frames),
                original_frames=original.frames,
            ),
        )
    return chunks


def _matches_target(
    buffer: AudioBuffer,
    sample_rate: int,
    channels: int,
    frames: int,
) -> bool:
    return (
        buffer.sample_rate == sample_rate
        and buffer.channels == channels
        and buffer.frames == frames
    )


def _current_stack_path(paths: ProjectPaths, settings: AppSettings) -> Path:
    return selected_source_path(paths, settings, "voice_stack") or paths.voice_stack_raw


def _write_stack_buffer(
    paths: ProjectPaths,
    settings: AppSettings,
    buffer: AudioBuffer,
    *,
    timestamped: bool,
) -> str | None:
    if timestamped:
        stack_path = _timestamped_stack_path(paths)
        write_wav_atomic(stack_path, buffer)
        relative_path = _relative_path(paths.root, stack_path)
        settings.sources.voice_stack_path = relative_path
        write_wav_atomic(paths.voice_stack_raw, buffer)
        return relative_path

    write_wav_atomic(paths.voice_stack_raw, buffer)
    return settings.sources.voice_stack_path


def _timestamped_stack_path(paths: ProjectPaths) -> Path:
    return next_voice_stack_path(paths)


def _relative_path(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _silent_buffer(frames: int, sample_rate: int, channels: int) -> AudioBuffer:
    samples = np.zeros((frames, channels), dtype=np.float32)
    return AudioBuffer(samples=samples, sample_rate=sample_rate)


def _read_manifest(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _test_library_entries(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    entries = manifest.get("entries", [])
    return [entry for entry in entries if entry.get("source_mode") == "test_library"]


def _accepted_clip_path(paths: ProjectPaths, accepted_clip_path: str) -> Path:
    path = Path(accepted_clip_path)
    if path.is_absolute():
        msg = "accepted_clip_path must be relative to the project root"
        raise ValueError(msg)

    resolved = (paths.root / path).resolve()
    accepted_root = paths.accepted_dir.resolve()
    if not resolved.is_relative_to(accepted_root):
        msg = "accepted_clip_path must stay under data/processed/accepted"
        raise ValueError(msg)
    return resolved


def _entry_offset(entry: dict[str, Any], target_frames: int) -> int:
    offset_frames = int(entry.get("offset_frames", 0))
    if not 0 <= offset_frames < target_frames:
        msg = "manifest offset_frames must be greater than or equal to 0 and less than loop length"
        raise ValueError(msg)
    return offset_frames


def _json_safe_snapshot(snapshot: Mapping[str, Any] | BaseModel | None) -> dict[str, Any]:
    if snapshot is None:
        return {}
    if isinstance(snapshot, BaseModel):
        raw = snapshot.model_dump(mode="json")
    else:
        raw = dict(snapshot)
    return json.loads(json.dumps(raw, ensure_ascii=False, default=str))


def _deterministic_offset(
    revision: int,
    existing_entry_count: int,
    chunk_index: int,
    loop_frames: int,
) -> int:
    seed = f"{revision}:{existing_entry_count}:{chunk_index}:{loop_frames}".encode()
    offset = int.from_bytes(sha256(seed).digest()[:8], "big") % loop_frames
    if offset == 0 and loop_frames > 1:
        return 1
    return offset


def _apply_gain(samples: np.ndarray, gain_db: float) -> np.ndarray:
    gain = 10 ** (gain_db / 20.0)
    return (samples.astype(np.float32, copy=False) * gain).astype(np.float32)


def _mix_wrapped(stack_samples: np.ndarray, chunk_samples: np.ndarray, offset_frames: int) -> None:
    loop_frames = stack_samples.shape[0]
    chunk_frames = chunk_samples.shape[0]
    end = offset_frames + chunk_frames
    if end <= loop_frames:
        stack_samples[offset_frames:end] += chunk_samples
        return

    first_length = loop_frames - offset_frames
    stack_samples[offset_frames:] += chunk_samples[:first_length]
    remaining = chunk_frames - first_length
    stack_samples[:remaining] += chunk_samples[first_length:]


def _apply_peak_guard(samples: np.ndarray) -> tuple[np.ndarray, float, float]:
    peak_before = _peak(samples)
    if peak_before <= _PEAK_CEILING:
        return samples.astype(np.float32, copy=True), peak_before, 0.0

    scale = _PEAK_CEILING / peak_before
    guarded = (samples * scale).astype(np.float32)
    peak_after = _peak(guarded)
    gain_reduction_db = 20 * log10(peak_before / peak_after)
    return guarded, peak_after, gain_reduction_db


def _peak(samples: np.ndarray) -> float:
    if samples.shape[0] == 0:
        return 0.0
    return float(np.max(np.abs(samples)))


def _cleanup_paths(paths: list[Path]) -> None:
    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def _restore_raw_stack(path: Path, previous_raw_bytes: bytes | None) -> None:
    if previous_raw_bytes is None:
        path.unlink(missing_ok=True)
        return

    temp_path = path.with_name(f".{path.stem}.{uuid4().hex}.rollback.tmp")
    try:
        temp_path.write_bytes(previous_raw_bytes)
        temp_path.replace(path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def _write_json_atomic(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.stem}.{uuid4().hex}.tmp")
    try:
        temp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temp_path.replace(path)
    finally:
        if temp_path.exists():
            temp_path.unlink()
