from __future__ import annotations

from pathlib import PurePosixPath
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

EqPointType = Literal["bell", "low_shelf", "high_shelf"]

GRAPH_EQ_MIN_HZ = 20.0
GRAPH_EQ_MAX_HZ = 20_000.0
GRAPH_EQ_MIN_GAIN_DB = -18.0
GRAPH_EQ_MAX_GAIN_DB = 18.0
GRAPH_EQ_MAX_POINTS = 8
GRAPH_EQ_DEFAULT_BELL_Q = 1.4
GRAPH_EQ_DEFAULT_SHELF_Q = 0.707


class EqPointSettings(BaseModel):
    id: str = Field(min_length=1)
    type: EqPointType
    frequency_hz: float = Field(ge=GRAPH_EQ_MIN_HZ, le=GRAPH_EQ_MAX_HZ)
    gain_db: float = Field(default=0.0, ge=GRAPH_EQ_MIN_GAIN_DB, le=GRAPH_EQ_MAX_GAIN_DB)
    q: float = Field(default=GRAPH_EQ_DEFAULT_BELL_Q, ge=0.1, le=18.0)

    @model_validator(mode="before")
    @classmethod
    def default_q_for_type(cls, data: object) -> object:
        if not isinstance(data, dict) or data.get("q") is not None:
            return data
        if data.get("type") in {"low_shelf", "high_shelf"}:
            return {**data, "q": GRAPH_EQ_DEFAULT_SHELF_Q}
        if data.get("type") == "bell":
            return {**data, "q": GRAPH_EQ_DEFAULT_BELL_Q}
        return data


def default_graph_eq_points() -> list[EqPointSettings]:
    return [
        EqPointSettings(
            id="low",
            type="low_shelf",
            frequency_hz=80.0,
            gain_db=0.0,
            q=GRAPH_EQ_DEFAULT_SHELF_Q,
        ),
        EqPointSettings(
            id="mid",
            type="bell",
            frequency_hz=1_000.0,
            gain_db=0.0,
            q=GRAPH_EQ_DEFAULT_BELL_Q,
        ),
        EqPointSettings(
            id="high",
            type="high_shelf",
            frequency_hz=10_000.0,
            gain_db=0.0,
            q=GRAPH_EQ_DEFAULT_SHELF_Q,
        ),
    ]


class EqSettings(BaseModel):
    points: list[EqPointSettings] = Field(default_factory=default_graph_eq_points)
    low_gain_db: float = Field(default=0.0, ge=-18.0, le=12.0)
    mid_gain_db: float = Field(default=0.0, ge=-18.0, le=12.0)
    high_gain_db: float = Field(default=0.0, ge=-18.0, le=12.0)
    highpass_hz: float = Field(default=20.0, ge=20.0, le=1_000.0)
    lowpass_hz: float = Field(default=20_000.0, ge=1_000.0, le=20_000.0)

    @model_validator(mode="after")
    def validate_graph_eq(self) -> EqSettings:
        if self.lowpass_hz <= self.highpass_hz:
            msg = "lowpass_hz must be greater than highpass_hz"
            raise ValueError(msg)
        if len(self.points) > GRAPH_EQ_MAX_POINTS:
            msg = f"points must contain at most {GRAPH_EQ_MAX_POINTS} items"
            raise ValueError(msg)
        point_ids = [point.id for point in self.points]
        if len(set(point_ids)) != len(point_ids):
            msg = "point ids must be unique"
            raise ValueError(msg)
        return self


class LayerSettings(BaseModel):
    enabled: bool = True
    volume_db: float = Field(default=-12.0, ge=-60.0, le=12.0)
    eq: EqSettings = Field(default_factory=EqSettings)


class AudioFormatSettings(BaseModel):
    sample_rate: int = Field(default=48_000, ge=8_000, le=192_000)
    channels: int = Field(default=2, ge=1, le=2)
    loop_seconds: int = Field(default=300, ge=1, le=600)
    peak_ceiling: float = Field(default=0.98, gt=0.0, le=1.0)


class InputControlSettings(BaseModel):
    armed: bool = False
    minimum_recording_seconds: float = Field(default=3.0, ge=0.0, le=30.0)
    maximum_recording_seconds: float = Field(default=120.0, ge=1.0, le=600.0)

    @model_validator(mode="after")
    def validate_recording_window(self) -> InputControlSettings:
        if self.maximum_recording_seconds <= self.minimum_recording_seconds:
            msg = "maximum_recording_seconds must be greater than minimum_recording_seconds"
            raise ValueError(msg)
        return self


class RecordingProcessingSettings(BaseModel):
    gain_db: float = Field(default=0.0, ge=-60.0, le=24.0)
    normalize_peak: float = Field(default=0.35, gt=0.0, le=1.0)
    highpass_hz: float = Field(default=90.0, ge=20.0, le=1_000.0)
    lowpass_hz: float = Field(default=8_000.0, ge=1_000.0, le=20_000.0)
    presence_gain_db: float = Field(default=-3.0, ge=-18.0, le=12.0)
    reverb_mix: float = Field(default=0.25, ge=0.0, le=1.0)
    delay_mix: float = Field(default=0.0, ge=0.0, le=1.0)
    fade_ms: int = Field(default=50, ge=0, le=5_000)

    @model_validator(mode="after")
    def validate_filter_order(self) -> RecordingProcessingSettings:
        if self.lowpass_hz <= self.highpass_hz:
            msg = "lowpass_hz must be greater than highpass_hz"
            raise ValueError(msg)
        return self


class DeviceSettings(BaseModel):
    input_device_id: str | None = None
    output_device_id: str | None = None


class PlaybackSettings(BaseModel):
    auto_start: bool = False
    apply_mode: Literal["stable", "live"] = "stable"
    master_volume_db: float = Field(default=-6.0, ge=-60.0, le=6.0)


class SourceSelectionSettings(BaseModel):
    low_path: str | None = None
    mid_path: str | None = None
    voice_raw_path: str | None = None
    voice_stack_path: str | None = None

    @field_validator("low_path", "mid_path", "voice_raw_path", "voice_stack_path")
    @classmethod
    def validate_source_path(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.replace("\\", "/").strip()
        path = PurePosixPath(normalized)
        if not normalized or path.is_absolute() or ".." in path.parts:
            msg = "source paths must be relative paths under the project root"
            raise ValueError(msg)
        if path.suffix.lower() != ".wav":
            msg = "source paths must point to .wav files"
            raise ValueError(msg)
        return path.as_posix()


class VoiceStackSettings(BaseModel):
    mode: Literal["test_library", "live_ephemeral"] = "live_ephemeral"
    loop_seconds: int = Field(default=60, ge=1, le=600)
    transition_seconds: int = Field(default=3, ge=0, le=10)
    placement: Literal["random"] = "random"
    insert_gain_db: float = Field(default=-12.0, ge=-60.0, le=12.0)


def default_layers() -> dict[str, LayerSettings]:
    return {
        "low": LayerSettings(enabled=True, volume_db=-12.0),
        "mid": LayerSettings(enabled=True, volume_db=-12.0),
        "voice": LayerSettings(enabled=True, volume_db=-18.0),
    }


class AppSettings(BaseModel):
    audio: AudioFormatSettings = Field(default_factory=AudioFormatSettings)
    input_control: InputControlSettings = Field(default_factory=InputControlSettings)
    recording: RecordingProcessingSettings = Field(default_factory=RecordingProcessingSettings)
    devices: DeviceSettings = Field(default_factory=DeviceSettings)
    playback: PlaybackSettings = Field(default_factory=PlaybackSettings)
    sources: SourceSelectionSettings = Field(default_factory=SourceSelectionSettings)
    voice_stack: VoiceStackSettings = Field(default_factory=VoiceStackSettings)
    layers: dict[str, LayerSettings] = Field(default_factory=default_layers)

    @model_validator(mode="after")
    def validate_required_layers(self) -> AppSettings:
        required = {"low", "mid", "voice"}
        if set(self.layers) != required:
            msg = "layers must contain exactly low, mid, and voice"
            raise ValueError(msg)
        return self
