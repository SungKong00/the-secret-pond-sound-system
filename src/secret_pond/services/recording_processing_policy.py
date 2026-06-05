from __future__ import annotations

from secret_pond.config import AppSettings


def recording_processing_sample_rate(settings: AppSettings, source_sample_rate: int) -> int:
    min_filter_rate = int(settings.recording.lowpass_hz * 2) + 2
    return max(settings.audio.sample_rate, source_sample_rate, min_filter_rate)
