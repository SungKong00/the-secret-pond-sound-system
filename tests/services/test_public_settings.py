from __future__ import annotations

from secret_pond.services.public_settings import PublicRecorderSettings


def test_public_settings_loads_environment(monkeypatch) -> None:
    monkeypatch.setenv("PUBLIC_RECORDING_TOKEN", "record-token")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "secret-password")
    monkeypatch.setenv("PUBLIC_MAX_UPLOAD_BYTES", "123456")
    monkeypatch.setenv("PUBLIC_STACK_LOCK_TIMEOUT_SECONDS", "7.5")

    settings = PublicRecorderSettings.from_env()

    assert settings.public_recording_token == "record-token"
    assert settings.admin_username == "admin"
    assert settings.admin_password == "secret-password"
    assert settings.max_upload_bytes == 123456
    assert settings.stack_lock_timeout_seconds == 7.5


def test_public_settings_uses_mvp_defaults(monkeypatch) -> None:
    monkeypatch.setenv("PUBLIC_RECORDING_TOKEN", "record-token")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "secret-password")
    monkeypatch.delenv("PUBLIC_MAX_UPLOAD_BYTES", raising=False)
    monkeypatch.delenv("PUBLIC_STACK_LOCK_TIMEOUT_SECONDS", raising=False)

    settings = PublicRecorderSettings.from_env()

    assert settings.max_upload_bytes == 25 * 1024 * 1024
    assert settings.stack_lock_timeout_seconds == 30.0
