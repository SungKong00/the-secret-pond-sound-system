from __future__ import annotations

import json
from pathlib import Path

import pytest

from secret_pond.config import (
    AppSettings,
    AudioFormatSettings,
    DeviceSettings,
    EqPointSettings,
    PlaybackSettings,
    SourceSelectionSettings,
)
from secret_pond.paths import ProjectPaths
from secret_pond.services.settings_presets import (
    PresetSourceMissingError,
    PresetStore,
)
from secret_pond.services.settings_store import SettingsState


def preset_ready_settings() -> AppSettings:
    base = AppSettings()
    layers = {
        **base.layers,
        "mid": base.layers["mid"].model_copy(
            update={
                "enabled": False,
                "volume_db": -9.0,
                "eq": base.layers["mid"].eq.model_copy(
                    update={
                        "points": [
                            EqPointSettings(
                                id="preset-mid",
                                type="bell",
                                frequency_hz=1_250.0,
                                gain_db=4.5,
                                q=1.4,
                            )
                        ]
                    }
                ),
            },
            deep=True,
        ),
    }
    return base.model_copy(
        update={
            "audio": AudioFormatSettings(sample_rate=96_000),
            "devices": DeviceSettings(input_device_id="do-not-save"),
            "playback": PlaybackSettings(apply_mode="live", master_volume_db=-3.0),
            "sources": SourceSelectionSettings(
                low_path="data/sources/low/opening-low.wav",
                mid_path="data/sources/mid/opening-mid.wav",
                voice_stack_path="data/sources/voice/stack/opening-voice.wav",
            ),
            "layers": layers,
        },
        deep=True,
    )


def create_preset_source_files(paths: ProjectPaths) -> None:
    for relative_path in (
        "data/sources/low/opening-low.wav",
        "data/sources/mid/opening-mid.wav",
        "data/sources/voice/stack/opening-voice.wav",
    ):
        path = paths.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"placeholder")


def test_preset_store_saves_draft_subset_without_runtime_fields(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path)
    draft = preset_ready_settings()

    preset = PresetStore(paths).create_from_draft("Opening", draft)
    raw = json.loads(paths.presets_file.read_text(encoding="utf-8"))

    assert preset.name == "Opening"
    assert raw["schema_version"] == 1
    assert raw["presets"][0]["name"] == "Opening"
    payload = raw["presets"][0]["payload"]
    assert set(payload) == {"layers", "playback", "sources", "voice_stack"}
    assert payload["playback"] == {"master_volume_db": -3.0}
    assert payload["sources"]["low_path"] == "data/sources/low/opening-low.wav"
    assert payload["layers"]["mid"]["volume_db"] == -9.0
    assert "audio" not in payload
    assert "devices" not in payload
    assert "input_control" not in payload
    assert "apply_mode" not in json.dumps(payload)


def test_preset_store_loads_preset_into_draft_without_changing_active(
    tmp_path: Path,
) -> None:
    paths = ProjectPaths(tmp_path)
    create_preset_source_files(paths)
    store = PresetStore(paths)
    active = AppSettings()
    preset = store.create_from_draft("Opening", preset_ready_settings())

    state = store.load_to_draft(
        preset.id,
        SettingsState(active=active, draft=AppSettings()),
    )

    assert state.active == active
    assert state.draft.sources.low_path == "data/sources/low/opening-low.wav"
    assert state.draft.layers["mid"].enabled is False
    assert state.draft.layers["mid"].volume_db == -9.0
    assert state.draft.playback.master_volume_db == -3.0
    assert state.draft.playback.apply_mode == "stable"
    assert state.draft.devices == active.devices
    assert state.draft.audio == active.audio


def test_preset_store_rejects_load_when_referenced_source_is_missing(
    tmp_path: Path,
) -> None:
    paths = ProjectPaths(tmp_path)
    store = PresetStore(paths)
    preset = store.create_from_draft("Opening", preset_ready_settings())

    with pytest.raises(PresetSourceMissingError) as error:
        store.load_to_draft(preset.id, SettingsState(active=AppSettings(), draft=AppSettings()))

    assert error.value.missing_sources == [
        "data/sources/low/opening-low.wav",
        "data/sources/mid/opening-mid.wav",
        "data/sources/voice/stack/opening-voice.wav",
    ]
