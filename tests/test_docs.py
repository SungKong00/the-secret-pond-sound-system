from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUEST_FILE = ROOT / "비밀의_연못_녹음_루프_자동화_개발요청서.txt"


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_operator_guide_covers_required_operations() -> None:
    guide = read_text(ROOT / "docs" / "operator-guide.md")

    required = [
        "macOS",
        "Windows PowerShell",
        "secret-pond doctor",
        "secret-pond doctor --json",
        "secret-pond doctor --strict",
        "secret-pond rebuild-test-library",
        "Microphone",
        "data/sources/low.wav",
        "data/sources/mid.wav",
        "http://127.0.0.1:8000",
        "Arm",
        "Disarm",
        "Spacebar",
        "browser blur",
        "Arm is unavailable while already armed",
        "Disarm is unavailable when already disarmed",
        "Apply and Restart",
        "Applying...",
        "Unsaved audio changes",
        "Restart Output",
        "Soft",
        "Misty",
        "Dense",
        "Clearer Voice",
        "Maintenance",
        "Reset Draft",
        "Reset Participants",
        "Stop recording before using Reset Draft",
        "Stop recording before using Reset Participants",
        "Apply and Restart is running",
        "Apply and Restart is unavailable while recording",
        "recording stop processing finishes",
        "test_library",
        "live_ephemeral",
        "data/processed/accepted",
        "data/voice/voice_stack_manifest.json",
        "data/voice/voice_stack_raw.wav",
        "data/config/settings.json",
        "data/logs",
        "device disappears",
        "renamed",
        "Restart the app",
        "Python 3.11 or 3.12",
        "loads existing compatible playback caches",
        "startup playback is unavailable",
        "Playback panel",
        "Voice Stack panel",
        "verify `secret-pond doctor` and dashboard warnings",
        "does not prove microphone permission",
        "Sync Live",
        "Sync Polling",
        "Error None",
        "Error Active",
        "Spacebar capture is ready",
        "Hold Space to Record",
        "active recording",
        "key-repeat start requests",
    ]
    for phrase in required:
        assert phrase in guide


def test_audio_setup_checklist_covers_manual_verification() -> None:
    checklist = read_text(ROOT / "docs" / "audio-setup-checklist.md")

    required = [
        "secret-pond doctor",
        "secret-pond doctor --json",
        "secret-pond doctor --strict",
        "missing-source warning",
        "valid low/mid files",
        "Startup loads compatible rendered playback caches",
        "Playback starts",
        "Low layer",
        "Mid layer",
        "Voice layer",
        "Disarmed",
        "Arm",
        "Spacebar",
        "shorter than 3 seconds",
        "participant count",
        "test_library",
        "live_ephemeral",
        "voice_stack_raw.wav",
        "secret-pond rebuild-test-library",
        "voice_playback.wav",
        "EQ slider",
        "Apply and Restart",
        "failed render",
        "settings",
        "macOS",
        "Windows",
        "CoreAudio",
        "WASAPI/MME",
        "file-locking",
        "spacebar does not scroll",
        "repeat start requests",
    ]
    for phrase in required:
        assert phrase in checklist


def test_readme_links_operator_docs() -> None:
    readme = read_text(ROOT / "README.md")

    assert "docs/operator-guide.md" in readme
    assert "docs/audio-setup-checklist.md" in readme
    assert "secret-pond doctor --json" in readme
    assert "secret-pond doctor --strict" in readme
    assert "secret-pond rebuild-test-library" in readme
    assert "Restart Output" in readme
    assert "Soft" in readme
    assert "Misty" in readme
    assert "Dense" in readme
    assert "Clearer Voice" in readme
    assert "Unsaved audio changes" in readme
    assert "min/max duration" in readme
    assert "System" in readme
    assert "렌더 캐시" in readme


def test_request_file_records_current_mvp_docs_decisions() -> None:
    request = read_text(REQUEST_FILE)

    assert "11) 현재 운영자 UI와 문서화 반영" in request
    assert "Restart Output" in request
    assert "Soft / Misty / Dense / Clearer Voice" in request
    assert "하드웨어 센서" in request
    assert "Apply and Restart" in request
    assert "앱 재시작" in request
    assert "기존 렌더 캐시는 활성 샘플레이트" in request
    assert "docs/operator-guide.md" in request
    assert "docs/audio-setup-checklist.md" in request
    assert "secret-pond doctor --json" in request
    assert "secret-pond doctor --strict" in request
    assert "secret-pond rebuild-test-library" in request
    assert "Maintenance" in request
    assert "Reset Draft" in request
    assert "녹음 중에는 Reset Draft" in request
    assert "Reset Participants" in request
    assert "Apply and Restart가 실행 중일 때" in request
    assert "Applying..." in request
    assert "목소리 렌더링까지 성공한 뒤에만 증가" in request
    assert "녹음 제어 실패 후에도 백엔드 상태를 다시 불러오도록 시도해" in request
    assert "녹음 종료 처리가 진행 중일 때" in request
    assert "녹음 종료 처리가 진행 중일 때는 Apply and Restart" in request
    assert "이미 Disarm 상태이고 녹음 중이 아닐 때는 Disarm 버튼" in request
    assert "keydown 반복" in request
    assert "이미 Arm 상태이거나 녹음 중일 때는 Arm 버튼" in request
    assert "Playback 패널" in request
    assert "Voice Stack 패널" in request
    assert "상태 동기화 배지" in request
    assert "오류 상태 배지" in request
    assert "Spacebar 캡처 준비 상태" in request
    assert "Hold Space to Record" in request
