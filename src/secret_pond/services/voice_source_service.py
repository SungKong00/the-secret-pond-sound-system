from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from secret_pond.audio.buffers import AudioBuffer
from secret_pond.audio.effects import apply_recording_processing
from secret_pond.audio.file_io import read_wav, write_wav_atomic
from secret_pond.audio.layers import LayerId
from secret_pond.audio.source_library import resolve_category_path
from secret_pond.audio.voice_stack_naming import next_voice_raw_path
from secret_pond.config import AppSettings
from secret_pond.paths import ProjectPaths
from secret_pond.services.recording_processing_policy import recording_processing_sample_rate


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

    def preview_layers(
        self,
        relative_path: str,
        settings: AppSettings,
    ) -> dict[LayerId, AudioBuffer]:
        source_path = resolve_category_path(self._paths, "voice_raw", relative_path)
        loaded = read_wav(source_path)
        source = loaded.to_canonical(
            sample_rate=recording_processing_sample_rate(settings, loaded.sample_rate),
            channels=settings.audio.channels,
        )
        treated = apply_recording_processing(source, settings.recording).to_canonical(
            sample_rate=settings.audio.sample_rate,
            channels=settings.audio.channels,
        )
        target_frames = settings.audio.sample_rate * settings.audio.loop_seconds
        voice = treated.to_frame_count(target_frames)
        silence = AudioBuffer(
            samples=voice.samples * 0.0,
            sample_rate=settings.audio.sample_rate,
        )
        return {"low": silence, "mid": silence, "voice": voice}


def _relative_path(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()
