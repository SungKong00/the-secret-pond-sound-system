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
    preserve_active_preview = bool(
        getattr(runtime, "voice_raw_preview_path", None) is not None
        and getattr(runtime.player, "is_playing", False),
    )
    if preserve_active_preview:
        runtime.player.replace_rendered_buffers(preview_layers)
    else:
        runtime.player.load_rendered_buffers(preview_layers)
    runtime.voice_raw_preview_layers = dict(preview_layers)
    runtime.player.set_peak_ceiling(settings.audio.peak_ceiling)
    for layer_id in ("low", "mid"):
        runtime.player.set_enabled(layer_id, False)
        runtime.player.set_realtime_trim(layer_id, 0.0)
    runtime.player.set_enabled("voice", True)
    runtime.player.set_realtime_trim("voice", 0.0)
    if not preserve_active_preview:
        runtime.player.restart()


def start_voice_raw_preview(
    runtime: Any,
    relative_path: str,
    settings: AppSettings,
) -> None:
    was_main_playback_running = runtime.output.is_running and runtime.voice_raw_preview_path is None
    if runtime.voice_raw_preview_path is not None:
        was_main_playback_running = bool(
            getattr(runtime, "voice_raw_preview_resume_main", False),
        )
    if runtime.output.is_running:
        runtime.output.stop()
    runtime.player.stop()
    prepare_voice_raw_preview(runtime, relative_path, settings)
    try:
        runtime.output.start()
    except Exception:
        runtime.player.stop()
        raise
    runtime.voice_raw_preview_path = relative_path
    runtime.voice_raw_preview_resume_main = was_main_playback_running


def restore_main_playback_after_voice_raw_preview(
    runtime: Any,
    settings: AppSettings,
) -> None:
    runtime.player.load_rendered_layers(rendered_layer_paths(runtime.paths))
    apply_player_layer_settings(runtime, settings)
    runtime.voice_raw_preview_path = None
    runtime.voice_raw_preview_resume_main = False
    runtime.voice_raw_preview_layers = None
