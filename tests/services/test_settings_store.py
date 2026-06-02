from __future__ import annotations

import json
from pathlib import Path

import pytest

from secret_pond.config import AppSettings
from secret_pond.paths import ProjectPaths
from secret_pond.services.settings_store import SettingsState, SettingsStore


def settings_with_voice_volume(volume_db: float) -> AppSettings:
    settings = AppSettings()
    layers = {
        **settings.layers,
        "voice": settings.layers["voice"].model_copy(update={"volume_db": volume_db}),
    }
    return settings.model_copy(update={"layers": layers}, deep=True)


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
