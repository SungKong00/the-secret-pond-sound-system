from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from secret_pond.audio.buffers import AudioBuffer
from secret_pond.audio.file_io import write_wav_atomic
from secret_pond.audio.voice_stack_naming import next_voice_raw_path
from secret_pond.config import AppSettings
from secret_pond.paths import ProjectPaths


@dataclass(frozen=True)
class VoiceSourceSaveResult:
    relative_path: str


class VoiceSourceService:
    def __init__(self, paths: ProjectPaths) -> None:
        self._paths = paths

    def save_recording_source(
        self,
        recording: AudioBuffer,
        settings: AppSettings,
    ) -> VoiceSourceSaveResult:
        canonical = recording.to_canonical(
            sample_rate=settings.audio.sample_rate,
            channels=settings.audio.channels,
        )
        path = next_voice_raw_path(self._paths)
        write_wav_atomic(path, canonical)
        return VoiceSourceSaveResult(relative_path=_relative_path(self._paths.root, path))


def _relative_path(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()
