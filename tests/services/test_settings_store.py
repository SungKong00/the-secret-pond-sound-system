from __future__ import annotations

import json
from pathlib import Path

import pytest

from secret_pond.config import AppSettings, DeviceSettings
from secret_pond.paths import ProjectPaths
from secret_pond.services.settings_store import SettingsState, SettingsStore


def settings_with_voice_volume(volume_db: float) -> AppSettings:
    settings = AppSettings()
    layers = {
        **settings.layers,
        "voice": settings.layers["voice"].model_copy(update={"volume_db": volume_db}),
    }
    return settings.model_copy(update={"layers": layers}, deep=True)


def settings_with_devices(
    *,
    input_device_id: str | None,
    output_device_id: str | None,
) -> AppSettings:
    return AppSettings().model_copy(
        update={
            "devices": DeviceSettings(
                input_device_id=input_device_id,
                output_device_id=output_device_id,
            )
        },
        deep=True,
    )


def test_settings_store_initializes_missing_file_with_defaults(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path)
    store = SettingsStore(paths)

    state = store.load()
    payload = json.loads(paths.settings_file.read_text(encoding="utf-8"))

    assert state.active == AppSettings()
    assert state.draft == AppSettings()
    assert payload["schema_version"] == 1
    assert payload["active"] == AppSettings().model_dump(mode="json")
    assert payload["draft"] == AppSettings().model_dump(mode="json")


def test_settings_store_loads_persisted_active_and_draft(tmp_path: Path) -> None:
    store = SettingsStore(ProjectPaths(tmp_path))
    active = settings_with_voice_volume(-24.0)
    draft = settings_with_voice_volume(-12.0)

    store.save(SettingsState(active=active, draft=draft))
    loaded = store.load()

    assert loaded.active.layers["voice"].volume_db == -24.0
    assert loaded.draft.layers["voice"].volume_db == -12.0


@pytest.mark.parametrize(
    "payload",
    [
        "not-json",
        "{}",
        '{"schema_version": 2, "active": {}, "draft": {}}',
        '{"schema_version": 1, "active": {}, "draft": {}}',
    ],
)
def test_settings_store_rejects_invalid_file_without_overwriting(
    tmp_path: Path,
    payload: str,
) -> None:
    paths = ProjectPaths(tmp_path)
    paths.ensure_directories()
    paths.settings_file.write_text(payload, encoding="utf-8")
    store = SettingsStore(paths)

    with pytest.raises(ValueError, match="settings"):
        store.load()

    assert paths.settings_file.read_text(encoding="utf-8") == payload


def test_settings_store_set_draft_does_not_change_active(tmp_path: Path) -> None:
    store = SettingsStore(ProjectPaths(tmp_path))
    draft = settings_with_voice_volume(-9.0)

    state = store.set_draft(draft)

    assert state.active == AppSettings()
    assert state.draft.layers["voice"].volume_db == -9.0
    assert store.load().active == AppSettings()


def test_settings_store_apply_draft_promotes_draft_to_active(tmp_path: Path) -> None:
    store = SettingsStore(ProjectPaths(tmp_path))
    draft = settings_with_voice_volume(-9.0)

    store.set_draft(draft)
    state = store.apply_draft()

    assert state.active.layers["voice"].volume_db == -9.0
    assert state.draft.layers["voice"].volume_db == -9.0


def test_settings_store_load_for_startup_promotes_restart_required_draft(
    tmp_path: Path,
) -> None:
    store = SettingsStore(ProjectPaths(tmp_path))
    draft = settings_with_devices(input_device_id="mic-2", output_device_id="speaker-2")
    store.set_draft(draft)

    state = store.load_for_startup()

    assert state.active.devices.input_device_id == "mic-2"
    assert state.active.devices.output_device_id == "speaker-2"
    assert state.draft.devices.input_device_id == "mic-2"
    assert store.load().active.devices.output_device_id == "speaker-2"


def test_settings_store_load_for_startup_keeps_non_runtime_draft_pending(
    tmp_path: Path,
) -> None:
    store = SettingsStore(ProjectPaths(tmp_path))
    store.set_draft(settings_with_voice_volume(-9.0))

    state = store.load_for_startup()

    assert state.active.layers["voice"].volume_db == -18.0
    assert state.draft.layers["voice"].volume_db == -9.0
    assert store.load().active.layers["voice"].volume_db == -18.0


def test_settings_store_load_for_startup_promotes_only_restart_required_fields(
    tmp_path: Path,
) -> None:
    store = SettingsStore(ProjectPaths(tmp_path))
    active = AppSettings()
    draft = settings_with_devices(input_device_id="mic-2", output_device_id="speaker-2")
    layers = {
        **draft.layers,
        "voice": draft.layers["voice"].model_copy(update={"volume_db": -9.0}),
    }
    draft = draft.model_copy(update={"layers": layers}, deep=True)
    store.save(SettingsState(active=active, draft=draft))

    state = store.load_for_startup()

    assert state.active.devices.input_device_id == "mic-2"
    assert state.active.devices.output_device_id == "speaker-2"
    assert state.active.layers["voice"].volume_db == -18.0
    assert state.draft.layers["voice"].volume_db == -9.0
    assert store.load().draft.layers["voice"].volume_db == -9.0


def test_settings_store_reset_draft_discards_unapplied_changes(tmp_path: Path) -> None:
    store = SettingsStore(ProjectPaths(tmp_path))
    active = settings_with_voice_volume(-21.0)
    draft = settings_with_voice_volume(-9.0)
    store.save(SettingsState(active=active, draft=draft))

    state = store.reset_draft()

    assert state.active.layers["voice"].volume_db == -21.0
    assert state.draft.layers["voice"].volume_db == -21.0


def test_settings_store_atomic_write_cleans_temp_file(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path)
    store = SettingsStore(paths)

    store.save(SettingsState(active=AppSettings(), draft=settings_with_voice_volume(-9.0)))

    assert list(paths.config_dir.glob("*.tmp")) == []


def test_settings_store_migrates_missing_source_selection_from_existing_schema(
    tmp_path: Path,
) -> None:
    paths = ProjectPaths(tmp_path)
    paths.ensure_directories()
    legacy_settings = AppSettings().model_dump(mode="json")
    legacy_settings.pop("sources")
    paths.settings_file.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "active": legacy_settings,
                "draft": legacy_settings,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    loaded = SettingsStore(paths).load()

    assert loaded.active.sources.low_path is None
    assert loaded.draft.sources.voice_stack_path is None
