from __future__ import annotations

from typing import Any

from secret_pond.config import AppSettings


def apply_player_settings(
    player: Any,
    settings: AppSettings,
    *,
    reset_realtime_trims: bool = False,
) -> None:
    for layer_id, layer_settings in settings.layers.items():
        if reset_realtime_trims and hasattr(player, "set_enabled_immediate"):
            player.set_enabled_immediate(layer_id, layer_settings.enabled)
        else:
            player.set_enabled(layer_id, layer_settings.enabled)
        if reset_realtime_trims:
            player.set_realtime_trim(layer_id, 0.0)
    player.set_peak_ceiling(settings.audio.peak_ceiling)


def apply_player_layer_settings(
    runtime: Any,
    settings: AppSettings,
    *,
    reset_realtime_trims: bool = False,
) -> None:
    apply_player_settings(
        runtime.player,
        settings,
        reset_realtime_trims=reset_realtime_trims,
    )


def apply_live_player_layer_controls(
    player: Any,
    *,
    previous: AppSettings,
    current: AppSettings,
) -> None:
    for layer_id, layer_settings in current.layers.items():
        previous_layer = previous.layers[layer_id]
        if layer_settings.enabled != previous_layer.enabled:
            if hasattr(player, "set_enabled_immediate"):
                player.set_enabled_immediate(layer_id, layer_settings.enabled)
            else:
                player.set_enabled(layer_id, layer_settings.enabled)
        volume_delta_db = layer_settings.volume_db - previous_layer.volume_db
        if volume_delta_db != 0.0:
            player.set_realtime_trim(layer_id, volume_delta_db)
