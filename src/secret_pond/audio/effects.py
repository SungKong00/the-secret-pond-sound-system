from __future__ import annotations

import numpy as np
from scipy.signal import butter, sosfilt

from secret_pond.audio.buffers import AudioBuffer
from secret_pond.config import RecordingProcessingSettings

_PRESENCE_CROSSOVER_HZ = 1_500.0


def apply_gain_db(buffer: AudioBuffer, gain_db: float) -> AudioBuffer:
    return AudioBuffer(
        samples=_apply_gain_samples(buffer.samples, gain_db),
        sample_rate=buffer.sample_rate,
    )


def normalize_peak(
    buffer: AudioBuffer,
    target_peak: float,
    max_gain_db: float = 12.0,
) -> AudioBuffer:
    """Boost quiet material toward target_peak without attenuating louder takes."""
    if not np.isfinite(target_peak) or target_peak <= 0.0 or target_peak > 1.0:
        msg = "target_peak must be greater than 0 and less than or equal to 1"
        raise ValueError(msg)
    if not np.isfinite(max_gain_db) or max_gain_db < 0.0:
        msg = "max_gain_db must be non-negative"
        raise ValueError(msg)

    samples = _normalize_peak_samples(buffer.samples, target_peak, max_gain_db)
    return AudioBuffer(samples=samples, sample_rate=buffer.sample_rate)


def apply_fade(buffer: AudioBuffer, fade_in_ms: float, fade_out_ms: float) -> AudioBuffer:
    if fade_in_ms < 0 or fade_out_ms < 0:
        msg = "fade durations must be non-negative"
        raise ValueError(msg)

    faded = _apply_fade_samples(buffer.samples, buffer.sample_rate, fade_in_ms, fade_out_ms)
    return AudioBuffer(samples=faded, sample_rate=buffer.sample_rate)


def apply_highpass(buffer: AudioBuffer, cutoff_hz: float, order: int = 4) -> AudioBuffer:
    return _apply_filter(buffer, cutoff_hz, "highpass", order)


def apply_lowpass(buffer: AudioBuffer, cutoff_hz: float, order: int = 4) -> AudioBuffer:
    return _apply_filter(buffer, cutoff_hz, "lowpass", order)


def apply_presence_tone(
    buffer: AudioBuffer,
    gain_db: float,
    crossover_hz: float = _PRESENCE_CROSSOVER_HZ,
) -> AudioBuffer:
    if gain_db == 0.0:
        return AudioBuffer(samples=buffer.samples.copy(), sample_rate=buffer.sample_rate)

    toned = _apply_presence_tone_samples(
        buffer.samples,
        buffer.sample_rate,
        gain_db,
        crossover_hz,
    )
    return AudioBuffer(samples=toned, sample_rate=buffer.sample_rate)


def apply_recording_processing(
    buffer: AudioBuffer,
    settings: RecordingProcessingSettings,
) -> AudioBuffer:
    samples = _apply_gain_samples(buffer.samples, settings.gain_db)
    samples = _normalize_peak_samples(samples, target_peak=settings.normalize_peak)
    samples = _apply_filter_samples(samples, buffer.sample_rate, settings.highpass_hz, "highpass")
    samples = _apply_filter_samples(samples, buffer.sample_rate, settings.lowpass_hz, "lowpass")
    samples = _apply_presence_tone_samples(samples, buffer.sample_rate, settings.presence_gain_db)
    # Reverb and delay are deferred for the MVP offline chain; settings remain
    # modeled so the UI/config contract does not need to change later.
    samples = _apply_fade_samples(samples, buffer.sample_rate, settings.fade_ms, settings.fade_ms)
    samples = _limit_peak_samples(samples)
    return AudioBuffer(samples=samples, sample_rate=buffer.sample_rate)


def _apply_filter(
    buffer: AudioBuffer,
    cutoff_hz: float,
    btype: str,
    order: int,
) -> AudioBuffer:
    _validate_cutoff(cutoff_hz, buffer.sample_rate)
    filtered = _apply_filter_samples(buffer.samples, buffer.sample_rate, cutoff_hz, btype, order)
    return AudioBuffer(samples=filtered, sample_rate=buffer.sample_rate)


def _apply_gain_samples(samples: np.ndarray, gain_db: float) -> np.ndarray:
    gain = 10 ** (gain_db / 20.0)
    return (samples.astype(np.float32, copy=True) * gain).astype(np.float32)


def _normalize_peak_samples(
    samples: np.ndarray,
    target_peak: float,
    max_gain_db: float = 12.0,
) -> np.ndarray:
    if not np.isfinite(target_peak) or target_peak <= 0.0 or target_peak > 1.0:
        msg = "target_peak must be greater than 0 and less than or equal to 1"
        raise ValueError(msg)
    if not np.isfinite(max_gain_db) or max_gain_db < 0.0:
        msg = "max_gain_db must be non-negative"
        raise ValueError(msg)

    normalized = samples.astype(np.float32, copy=True)
    if normalized.shape[0] == 0:
        return normalized

    peak = float(np.max(np.abs(normalized)))
    if peak == 0.0 or peak >= target_peak:
        return normalized

    required_gain = target_peak / peak
    capped_gain = min(required_gain, 10 ** (max_gain_db / 20.0))
    return (normalized * capped_gain).astype(np.float32)


def _apply_filter_samples(
    samples: np.ndarray,
    sample_rate: int,
    cutoff_hz: float,
    btype: str,
    order: int = 4,
) -> np.ndarray:
    _validate_cutoff(cutoff_hz, sample_rate)
    sos = butter(order, cutoff_hz, btype=btype, fs=sample_rate, output="sos")
    return sosfilt(sos, samples, axis=0).astype(np.float32)


def _apply_presence_tone_samples(
    samples: np.ndarray,
    sample_rate: int,
    gain_db: float,
    crossover_hz: float = _PRESENCE_CROSSOVER_HZ,
) -> np.ndarray:
    if gain_db == 0.0:
        return samples.astype(np.float32, copy=True)

    _validate_cutoff(crossover_hz, sample_rate)
    low = _apply_filter_samples(samples, sample_rate, crossover_hz, "lowpass")
    high = _apply_filter_samples(samples, sample_rate, crossover_hz, "highpass")
    high_gain = 10 ** (gain_db / 20.0)
    return (low + (high * high_gain)).astype(np.float32)


def _apply_fade_samples(
    samples: np.ndarray,
    sample_rate: int,
    fade_in_ms: float,
    fade_out_ms: float,
) -> np.ndarray:
    faded = samples.astype(np.float32, copy=True)
    if faded.shape[0] == 0:
        return faded

    envelope = np.ones(faded.shape[0], dtype=np.float32)
    fade_in_frames = _ms_to_frames(fade_in_ms, sample_rate, faded.shape[0])
    fade_out_frames = _ms_to_frames(fade_out_ms, sample_rate, faded.shape[0])

    if fade_in_frames > 0:
        envelope[:fade_in_frames] *= np.linspace(0.0, 1.0, fade_in_frames, dtype=np.float32)
    if fade_out_frames > 0:
        envelope[-fade_out_frames:] *= np.linspace(1.0, 0.0, fade_out_frames, dtype=np.float32)

    if faded.ndim == 1:
        return faded * envelope
    return faded * envelope[:, np.newaxis]


def _limit_peak_samples(samples: np.ndarray, peak_ceiling: float = 1.0) -> np.ndarray:
    limited = samples.astype(np.float32, copy=True)
    if limited.shape[0] == 0:
        return limited

    peak = float(np.max(np.abs(limited)))
    if peak <= peak_ceiling:
        return limited
    return (limited * (peak_ceiling / peak)).astype(np.float32)


def _validate_cutoff(cutoff_hz: float, sample_rate: int) -> None:
    nyquist = sample_rate / 2
    if not np.isfinite(cutoff_hz) or cutoff_hz <= 0 or cutoff_hz >= nyquist:
        msg = f"cutoff_hz must be greater than 0 and less than Nyquist ({nyquist})"
        raise ValueError(msg)


def _ms_to_frames(milliseconds: float, sample_rate: int, max_frames: int) -> int:
    frames = int(round(sample_rate * (milliseconds / 1000.0)))
    return min(frames, max_frames)
