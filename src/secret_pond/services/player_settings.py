from __future__ import annotations

from typing import Any

from secret_pond.config import AppSettings


def apply_player_settings(player: Any, settings: AppSettings) -> None:
    for layer_id, layer_settings in settings.layers.items():
        player.set_enabled(layer_id, layer_settings.enabled)
    player.set_peak_ceiling(settings.audio.peak_ceiling)


def apply_player_layer_settings(runtime: Any, settings: AppSettings) -> None:
    apply_player_settings(runtime.player, settings)
