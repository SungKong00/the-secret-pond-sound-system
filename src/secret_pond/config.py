from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class EqSettings(BaseModel):
    low_gain_db: float = Field(default=0.0, ge=-18.0, le=12.0)
    mid_gain_db: float = Field(default=0.0, ge=-18.0, le=12.0)
    high_gain_db: float = Field(default=0.0, ge=-18.0, le=12.0)
    highpass_hz: float = Field(default=20.0, ge=20.0, le=1_000.0)
    lowpass_hz: float = Field(default=20_000.0, ge=1_000.0, le=20_000.0)

    @model_validator(mode="after")
    def validate_filter_order(self) -> EqSettings:
        if self.lowpass_hz <= self.highpass_hz:
            msg = "lowpass_hz must be greater than highpass_hz"
            raise ValueError(msg)
        return self


class LayerSettings(BaseModel):
    enabled: bool = True
    volume_db: float = Field(default=-12.0, ge=-60.0, le=6.0)
    eq: EqSettings = Field(default_factory=EqSettings)


class AudioFormatSettings(BaseModel):
    sample_rate: int = Field(default=48_000, ge=8_000, le=192_000)
    channels: int = Field(default=2, ge=1, le=2)
    loop_seconds: int = Field(default=300, ge=30, le=600)
    peak_ceiling: float = Field(default=0.98, gt=0.0, le=1.0)


class InputControlSettings(BaseModel):
    armed: bool = False
    minimum_recording_seconds: float = Field(default=3.0, ge=0.0, le=30.0)
    maximum_recording_seconds: float = Field(default=60.0, ge=1.0, le=600.0)

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
    master_volume_db: float = Field(default=-6.0, ge=-60.0, le=6.0)


class VoiceStackSettings(BaseModel):
    placement: Literal["random"] = "random"
    insert_gain_db: float = Field(default=-12.0, ge=-60.0, le=6.0)


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
    voice_stack: VoiceStackSettings = Field(default_factory=VoiceStackSettings)
    layers: dict[str, LayerSettings] = Field(default_factory=default_layers)

    @model_validator(mode="after")
    def validate_required_layers(self) -> AppSettings:
        required = {"low", "mid", "voice"}
        if set(self.layers) != required:
            msg = "layers must contain exactly low, mid, and voice"
            raise ValueError(msg)
        return self
