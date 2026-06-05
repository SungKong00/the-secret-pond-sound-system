from __future__ import annotations

from typing import Any

from secret_pond.config import AppSettings
from secret_pond.services.player_settings import apply_player_layer_settings
from secret_pond.services.runtime import rendered_layer_paths


def prepare_voice_raw_preview(
    runtime: Any,
    relative_path: str,
    settings: AppSettings,
) -> None:
    preview_layers = runtime.voice_source.preview_layers(relative_path, settings)
    runtime.player.load_rendered_buffers(preview_layers)
    runtime.player.set_peak_ceiling(settings.audio.peak_ceiling)
    for layer_id in ("low", "mid"):
        runtime.player.set_enabled(layer_id, False)
        runtime.player.set_realtime_trim(layer_id, 0.0)
    runtime.player.set_enabled("voice", True)
    runtime.player.set_realtime_trim("voice", 0.0)
    runtime.player.restart()


def restore_main_playback_after_voice_raw_preview(
    runtime: Any,
    settings: AppSettings,
) -> None:
    runtime.player.load_rendered_layers(rendered_layer_paths(runtime.paths))
    apply_player_layer_settings(runtime, settings)
    runtime.voice_raw_preview_path = None
