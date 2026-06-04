from __future__ import annotations

from pathlib import Path

from secret_pond.paths import ProjectPaths


def test_project_paths_are_rooted_under_data_directory(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path)

    assert paths.data_dir == tmp_path / "data"
    assert paths.sources_dir == tmp_path / "data" / "sources"
    assert paths.low_source == tmp_path / "data" / "sources" / "low.wav"
    assert paths.mid_source == tmp_path / "data" / "sources" / "mid.wav"
    assert paths.low_sources_dir == tmp_path / "data" / "sources" / "low"
    assert paths.mid_sources_dir == tmp_path / "data" / "sources" / "mid"
    assert paths.voice_raw_sources_dir == tmp_path / "data" / "sources" / "voice" / "raw"
    assert paths.voice_stack_sources_dir == tmp_path / "data" / "sources" / "voice" / "stack"
    assert paths.voice_manifest == tmp_path / "data" / "voice" / "voice_stack_manifest.json"
    assert paths.participant_count_file == tmp_path / "data" / "logs" / "participants.json"


def test_ensure_directories_creates_runtime_directories(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path)

    paths.ensure_directories()

    assert paths.sources_dir.is_dir()
    assert paths.low_sources_dir.is_dir()
    assert paths.mid_sources_dir.is_dir()
    assert paths.voice_raw_sources_dir.is_dir()
    assert paths.voice_stack_sources_dir.is_dir()
    assert paths.accepted_dir.is_dir()
    assert paths.rendered_layers_dir.is_dir()
    assert paths.config_dir.is_dir()
