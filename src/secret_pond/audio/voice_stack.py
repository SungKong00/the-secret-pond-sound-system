from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import numpy as np

from secret_pond.audio.buffers import AudioBuffer
from secret_pond.audio.file_io import read_wav, write_wav_atomic
from secret_pond.config import AppSettings
from secret_pond.paths import ProjectPaths


@dataclass(frozen=True)
class VoiceStackSnapshot:
    buffer: AudioBuffer
    raw_created: bool
    raw_normalized: bool
    manifest_created: bool


class VoiceStackStore:
    def __init__(self, paths: ProjectPaths) -> None:
        self._paths = paths

    def ensure_initialized(self, settings: AppSettings) -> VoiceStackSnapshot:
        self._paths.ensure_directories()

        target_frames = settings.audio.sample_rate * settings.voice_stack.loop_seconds
        raw_created = False
        raw_normalized = False

        if self._paths.voice_stack_raw.exists():
            loaded = read_wav(self._paths.voice_stack_raw)
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
                write_wav_atomic(self._paths.voice_stack_raw, buffer)
        else:
            raw_created = True
            buffer = _silent_buffer(
                frames=target_frames,
                sample_rate=settings.audio.sample_rate,
                channels=settings.audio.channels,
            )
            write_wav_atomic(self._paths.voice_stack_raw, buffer)

        manifest_created = self._ensure_manifest()
        return VoiceStackSnapshot(
            buffer=buffer,
            raw_created=raw_created,
            raw_normalized=raw_normalized,
            manifest_created=manifest_created,
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


def _silent_buffer(frames: int, sample_rate: int, channels: int) -> AudioBuffer:
    samples = np.zeros((frames, channels), dtype=np.float32)
    return AudioBuffer(samples=samples, sample_rate=sample_rate)


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
