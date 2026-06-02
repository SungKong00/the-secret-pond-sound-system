from __future__ import annotations

from typing import Literal

LayerId = Literal["low", "mid", "voice"]
LAYER_IDS: tuple[LayerId, ...] = ("low", "mid", "voice")
