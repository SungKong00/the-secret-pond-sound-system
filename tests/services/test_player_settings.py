from __future__ import annotations

from types import SimpleNamespace

from secret_pond.audio.player import LayeredLoopPlayer
from secret_pond.config import AppSettings
from secret_pond.services.player_settings import apply_player_layer_settings


def test_apply_player_layer_settings_updates_enabled_layers_and_peak_ceiling() -> None:
    settings = AppSettings()
    layers = {
        **settings.layers,
        "voice": settings.layers["voice"].model_copy(update={"enabled": False}),
    }
    settings = settings.model_copy(
        update={
            "audio": settings.audio.model_copy(update={"peak_ceiling": 0.5}),
            "layers": layers,
        },
        deep=True,
    )
    player = LayeredLoopPlayer()

    apply_player_layer_settings(SimpleNamespace(player=player), settings)

    snapshot = player.snapshot()
    assert snapshot.states["voice"].enabled is False
    assert snapshot.peak_ceiling == 0.5
