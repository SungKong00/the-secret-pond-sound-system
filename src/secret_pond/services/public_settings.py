from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class PublicRecorderSettings:
    public_recording_token: str
    admin_username: str
    admin_password: str
    max_upload_bytes: int = 25 * 1024 * 1024
    stack_lock_timeout_seconds: float = 30.0
    minimum_duration_seconds: float = 3.0
    maximum_duration_seconds: float = 600.0

    @classmethod
    def from_env(cls) -> PublicRecorderSettings:
        return cls(
            public_recording_token=_required_env("PUBLIC_RECORDING_TOKEN"),
            admin_username=_required_env("ADMIN_USERNAME"),
            admin_password=_required_env("ADMIN_PASSWORD"),
            max_upload_bytes=int(os.environ.get("PUBLIC_MAX_UPLOAD_BYTES", 25 * 1024 * 1024)),
            stack_lock_timeout_seconds=float(
                os.environ.get("PUBLIC_STACK_LOCK_TIMEOUT_SECONDS", "30.0")
            ),
        )


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if value is None or not value.strip():
        msg = f"{name} is required"
        raise RuntimeError(msg)
    return value.strip()
