from __future__ import annotations

from dataclasses import dataclass

from secret_pond.audio.effects import apply_recording_processing
from secret_pond.audio.file_io import read_wav
from secret_pond.audio.source_library import resolve_category_path
from secret_pond.audio.voice_stack import VoiceStackAddResult, VoiceStackStore
from secret_pond.config import AppSettings
from secret_pond.paths import ProjectPaths
from secret_pond.services.recording_processing_policy import recording_processing_sample_rate


@dataclass(frozen=True)
class AddVoiceSourceToStackResult:
    stack_result: VoiceStackAddResult
    selected_voice_stack_path: str | None


class VoiceStackService:
    def __init__(self, paths: ProjectPaths, store: VoiceStackStore) -> None:
        self._paths = paths
        self._store = store

    def add_vr_to_stack(
        self,
        vr_relative_path: str,
        settings: AppSettings,
    ) -> AddVoiceSourceToStackResult:
        source_path = resolve_category_path(self._paths, "voice_raw", vr_relative_path)
        loaded = read_wav(source_path)
        source = loaded.to_canonical(
            sample_rate=recording_processing_sample_rate(settings, loaded.sample_rate),
            channels=settings.audio.channels,
        )
        treated = apply_recording_processing(source, settings.recording)
        stack_settings = settings.model_copy(deep=True)
        stack_settings.sources.voice_raw_path = vr_relative_path
        stack_settings.voice_stack.mode = "live_ephemeral"
        stack_result = self._store.add_processed_voice(
            treated,
            stack_settings,
            processing_settings_snapshot=settings.recording.model_dump(mode="json"),
        )
        settings.sources.voice_raw_path = vr_relative_path
        settings.sources.voice_stack_path = stack_result.voice_stack_path
        return AddVoiceSourceToStackResult(
            stack_result=stack_result,
            selected_voice_stack_path=stack_result.voice_stack_path,
        )
