from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import soundfile as sf

from secret_pond.audio.buffers import AudioBuffer


def read_wav(path: Path) -> AudioBuffer:
    samples, sample_rate = sf.read(path, dtype="float32", always_2d=True)
    return AudioBuffer(samples=samples, sample_rate=int(sample_rate))


def write_wav_atomic(path: Path, buffer: AudioBuffer) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.stem}.{uuid4().hex}.tmp.wav")
    try:
        sf.write(temp_path, buffer.clipped().samples, buffer.sample_rate, subtype="PCM_24")
        temp_path.replace(path)
    finally:
        if temp_path.exists():
            temp_path.unlink()
