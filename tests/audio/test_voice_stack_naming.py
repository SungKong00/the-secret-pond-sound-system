from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from secret_pond.audio.voice_stack_naming import (
    next_voice_raw_path,
    next_voice_stack_path,
    voice_recording_filename,
    voice_stack_filename,
)
from secret_pond.paths import ProjectPaths


def test_voice_recording_filename_formats_non_kst_time_in_kst() -> None:
    filename = voice_recording_filename(datetime(2026, 6, 4, 17, 23, 45, tzinfo=UTC))

    assert filename == "VR0605_022345.wav"


def test_voice_stack_filename_formats_non_kst_time_in_kst() -> None:
    filename = voice_stack_filename(datetime(2026, 6, 4, 17, 23, 45, tzinfo=UTC))

    assert filename == "VS0605_022345.wav"


def test_next_voice_raw_path_uses_kst_vr_name(tmp_path):
    paths = ProjectPaths(tmp_path)
    now = datetime(2026, 6, 10, 21, 31, 12, tzinfo=ZoneInfo("Asia/Seoul"))

    path = next_voice_raw_path(paths, now=now)

    assert path == paths.voice_raw_sources_dir / "VR0610_213112.wav"


def test_next_voice_stack_path_uses_kst_vs_name(tmp_path):
    paths = ProjectPaths(tmp_path)
    now = datetime(2026, 6, 10, 21, 31, 12, tzinfo=ZoneInfo("Asia/Seoul"))

    path = next_voice_stack_path(paths, now=now)

    assert path == paths.voice_stack_sources_dir / "VS0610_213112.wav"


def test_voice_name_collision_suffixes_start_at_two(tmp_path):
    paths = ProjectPaths(tmp_path)
    paths.ensure_directories()
    now = datetime(2026, 6, 10, 21, 31, 12, tzinfo=ZoneInfo("Asia/Seoul"))
    (paths.voice_raw_sources_dir / "VR0610_213112.wav").write_bytes(b"one")
    (paths.voice_raw_sources_dir / "VR0610_213112_2.wav").write_bytes(b"two")

    path = next_voice_raw_path(paths, now=now)

    assert path == paths.voice_raw_sources_dir / "VR0610_213112_3.wav"


def test_voice_name_collision_suffixes_are_deterministic_for_repeated_generations(
    tmp_path,
):
    paths = ProjectPaths(tmp_path)
    paths.ensure_directories()
    now = datetime(2026, 6, 10, 21, 31, 12, tzinfo=ZoneInfo("Asia/Seoul"))

    generated_paths = []
    for _ in range(4):
        path = next_voice_stack_path(paths, now=now)
        path.write_bytes(b"reserved")
        generated_paths.append(path.name)

    assert generated_paths == [
        "VS0610_213112.wav",
        "VS0610_213112_2.wav",
        "VS0610_213112_3.wav",
        "VS0610_213112_4.wav",
    ]
