from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ProjectPaths:
    root: Path

    def __post_init__(self) -> None:
        object.__setattr__(self, "root", Path(self.root))

    @property
    def data_dir(self) -> Path:
        return self.root / "data"

    @property
    def sources_dir(self) -> Path:
        return self.data_dir / "sources"

    @property
    def low_source(self) -> Path:
        return self.sources_dir / "low.wav"

    @property
    def mid_source(self) -> Path:
        return self.sources_dir / "mid.wav"

    @property
    def low_sources_dir(self) -> Path:
        return self.sources_dir / "low"

    @property
    def mid_sources_dir(self) -> Path:
        return self.sources_dir / "mid"

    @property
    def voice_sources_dir(self) -> Path:
        return self.sources_dir / "voice"

    @property
    def voice_raw_sources_dir(self) -> Path:
        return self.voice_sources_dir / "raw"

    @property
    def voice_stack_sources_dir(self) -> Path:
        return self.voice_sources_dir / "stack"

    @property
    def accepted_dir(self) -> Path:
        return self.data_dir / "processed" / "accepted"

    @property
    def voice_dir(self) -> Path:
        return self.data_dir / "voice"

    @property
    def voice_manifest(self) -> Path:
        return self.voice_dir / "voice_stack_manifest.json"

    @property
    def voice_stack_raw(self) -> Path:
        return self.voice_dir / "voice_stack_raw.wav"

    @property
    def rendered_layers_dir(self) -> Path:
        return self.data_dir / "rendered" / "layers"

    @property
    def low_playback(self) -> Path:
        return self.rendered_layers_dir / "low_playback.wav"

    @property
    def mid_playback(self) -> Path:
        return self.rendered_layers_dir / "mid_playback.wav"

    @property
    def voice_playback(self) -> Path:
        return self.rendered_layers_dir / "voice_playback.wav"

    @property
    def recordings_temp_dir(self) -> Path:
        return self.data_dir / "recordings_temp"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def participant_count_file(self) -> Path:
        return self.logs_dir / "participants.json"

    @property
    def event_log_file(self) -> Path:
        return self.logs_dir / "events.jsonl"

    @property
    def config_dir(self) -> Path:
        return self.data_dir / "config"

    @property
    def settings_file(self) -> Path:
        return self.config_dir / "settings.json"

    def ensure_directories(self) -> None:
        for directory in (
            self.sources_dir,
            self.low_sources_dir,
            self.mid_sources_dir,
            self.voice_raw_sources_dir,
            self.voice_stack_sources_dir,
            self.accepted_dir,
            self.voice_dir,
            self.rendered_layers_dir,
            self.recordings_temp_dir,
            self.logs_dir,
            self.config_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)
