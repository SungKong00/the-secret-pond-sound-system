from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from secret_pond.public_app import create_public_app


def test_public_recorder_renders_for_valid_token(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PUBLIC_RECORDING_TOKEN", "record-token")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "secret-password")

    client = TestClient(create_public_app(root=tmp_path))

    response = client.get("/r/record-token")

    assert response.status_code == 200
    assert "Voice Stack" in response.text
    assert "operator" not in response.text.lower()


def test_public_recorder_rejects_wrong_token(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PUBLIC_RECORDING_TOKEN", "record-token")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "secret-password")

    client = TestClient(create_public_app(root=tmp_path))

    response = client.get("/r/wrong-token")

    assert response.status_code == 404


def test_public_recording_upload_rejects_too_large_file(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("PUBLIC_RECORDING_TOKEN", "record-token")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "secret-password")
    monkeypatch.setenv("PUBLIC_MAX_UPLOAD_BYTES", "4")

    client = TestClient(create_public_app(root=tmp_path))

    response = client.post(
        "/api/public/recordings",
        headers={"X-Public-Recording-Token": "record-token"},
        files={"file": ("take.webm", b"12345", "audio/webm")},
    )

    assert response.status_code == 413
    assert response.json()["detail"] == "file_too_large"
