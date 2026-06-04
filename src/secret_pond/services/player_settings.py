from __future__ import annotations

from secret_pond.config import AppSettings
from secret_pond.services.runtime import SecretPondRuntime


def apply_player_layer_settings(runtime: SecretPondRuntime, settings: AppSettings) -> None:
    for layer_id, layer_settings in settings.layers.items():
        runtime.player.set_enabled(layer_id, layer_settings.enabled)
