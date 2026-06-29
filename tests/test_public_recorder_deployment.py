from __future__ import annotations

from pathlib import Path

from secret_pond.public_app import create_public_app


def test_public_app_uses_app_data_dir_from_environment(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("PUBLIC_RECORDING_TOKEN", "record-token")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "secret-password")
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))

    app = create_public_app()

    assert app.state.paths.root == tmp_path


def test_public_recorder_deployment_files_define_render_runtime() -> None:
    dockerfile = Path("Dockerfile.public-recorder").read_text(encoding="utf-8")
    render_config = Path("render.yaml").read_text(encoding="utf-8")

    assert "ffmpeg" in dockerfile
    assert "uvicorn" in dockerfile
    assert "secret_pond.public_app:create_public_app" in dockerfile
    assert "0.0.0.0" in dockerfile
    assert "Dockerfile.public-recorder" in render_config
    assert "PUBLIC_RECORDING_TOKEN" in render_config
    assert "ADMIN_USERNAME" in render_config
    assert "ADMIN_PASSWORD" in render_config
    assert "PUBLIC_MAX_UPLOAD_BYTES" in render_config
    assert "PUBLIC_STACK_LOCK_TIMEOUT_SECONDS" in render_config
    assert "APP_DATA_DIR" in render_config
    assert "/var/data" in render_config
    assert "sizeGB: 1" in render_config


def test_operator_doc_covers_public_recorder_manual_steps() -> None:
    doc = Path("docs/operator-public-recorder.md").read_text(encoding="utf-8")

    assert "Render 배포 체크리스트" in doc
    assert "Dockerfile.public-recorder" in doc
    assert "render.yaml" in doc
    assert "Persistent Disk" in doc
    assert "APP_DATA_DIR=/var/data" in doc
    assert "PUBLIC_MAX_UPLOAD_BYTES=26214400" in doc
    assert "PUBLIC_STACK_LOCK_TIMEOUT_SECONDS=30" in doc
    assert "public-recorder-init-seed" in doc
    assert "PUBLIC_RECORDING_TOKEN" in doc
    assert "ADMIN_USERNAME" in doc
    assert "ADMIN_PASSWORD" in doc
    assert "Basic Auth" in doc
    assert "/admin" in doc
    assert "/admin/versions" in doc
    assert "/admin/versions/upload" in doc
    assert "/admin/versions/latest/download" in doc
    assert "Upload Voice Stack" in doc
    assert "새 최신 누적 스택" in doc
    assert "미리듣기" in doc
    assert "삭제" in doc
    assert "삭제되지 않은 최신" in doc
    assert "러프 음량 보정" in doc
    assert "RMS" in doc
    assert "3초" in doc
    assert "10분" in doc
    assert "25MB" in doc
    assert "녹음 원본 파일은 저장하지 않습니다" in doc
    assert "iOS Safari" in doc
    assert "Android Chrome" in doc
    assert "마이크 권한" in doc
    assert "3초 전에는 녹음 중지" in doc
    assert "Voice Stack에 추가" in doc
    assert "수집 종료" in doc


def test_public_recorder_plan_has_no_stale_silent_detection_or_20_second_examples() -> None:
    plan = Path("docs/superpowers/plans/2026-06-28-public-voice-stack-recorder.md").read_text(
        encoding="utf-8"
    )

    assert "server rejects too short, empty, or silent input" not in plan
    assert "is_effectively_silent" not in plan
    assert "analyze_audio_levels" not in plan
    assert "silent.wav" not in plan
    assert "match=\"silent\"" not in plan
    assert "maximum_recording_seconds=20.0" not in plan
    assert "maximum_recording_seconds=20" not in plan
