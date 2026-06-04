from __future__ import annotations

from secret_pond.config import AppSettings, DeviceSettings
from secret_pond.services.settings_changes import (
    classify_settings_change,
    promote_runtime_config,
    runtime_config_field_names,
)


def test_runtime_config_field_names_exposes_classification_policy() -> None:
    assert runtime_config_field_names() == [
        "audio.sample_rate",
        "audio.channels",
        "devices.input_device_id",
        "devices.output_device_id",
    ]


def test_classify_settings_change_reports_runtime_config_fields_and_sections() -> None:
    active = AppSettings()
    draft = active.model_copy(
        update={
            "audio": active.audio.model_copy(update={"sample_rate": 44_100}),
            "devices": DeviceSettings(input_device_id="mic-2", output_device_id="speaker-2"),
        },
        deep=True,
    )

    plan = classify_settings_change(active, draft)

    assert plan.runtime_config_changed is True
    assert plan.changed_runtime_fields == [
        "audio.sample_rate",
        "devices.input_device_id",
        "devices.output_device_id",
    ]
    assert plan.changed_sections == ["audio", "devices"]


def test_classify_settings_change_keeps_mix_changes_render_only() -> None:
    active = AppSettings()
    layers = {
        **active.layers,
        "voice": active.layers["voice"].model_copy(update={"volume_db": -9.0}),
    }
    draft = active.model_copy(update={"layers": layers}, deep=True)

    plan = classify_settings_change(active, draft)

    assert plan.runtime_config_changed is False
    assert plan.changed_runtime_fields == []
    assert plan.changed_sections == ["layers"]


def test_classify_settings_change_reports_noop_plan_for_identical_settings() -> None:
    settings = AppSettings()

    plan = classify_settings_change(settings, settings)

    assert plan.runtime_config_changed is False
    assert plan.changed_runtime_fields == []
    assert plan.changed_sections == []


def test_promote_runtime_config_clears_only_runtime_fields() -> None:
    active = AppSettings()
    layers = {
        **active.layers,
        "voice": active.layers["voice"].model_copy(update={"volume_db": -9.0}),
    }
    draft = active.model_copy(
        update={
            "audio": active.audio.model_copy(
                update={"sample_rate": 44_100, "channels": 1, "loop_seconds": 120},
            ),
            "devices": DeviceSettings(input_device_id="mic-2", output_device_id="speaker-2"),
            "layers": layers,
        },
        deep=True,
    )

    promoted = promote_runtime_config(active, draft)
    plan = classify_settings_change(promoted, draft)

    assert promoted.audio.sample_rate == 44_100
    assert promoted.audio.channels == 1
    assert promoted.devices.input_device_id == "mic-2"
    assert promoted.devices.output_device_id == "speaker-2"
    assert promoted.audio.loop_seconds == active.audio.loop_seconds
    assert promoted.layers["voice"].volume_db == active.layers["voice"].volume_db
    assert plan.changed_runtime_fields == []
    assert plan.changed_sections == ["audio", "layers"]
