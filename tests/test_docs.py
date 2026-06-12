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
        "Start Secret Pond.command",
        "Start Secret Pond.bat",
        "secret-pond doctor",
        "secret-pond doctor --json",
        "secret-pond doctor --strict",
        "secret-pond rebuild-test-library",
        "Microphone",
        "data/sources/low.wav",
        "data/sources/mid.wav",
        "data/sources/low/*.wav",
        "data/sources/mid/*.wav",
        "data/sources/voice/raw/*.wav",
        "data/sources/voice/stack/*.wav",
        "Source Library",
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
        "Cancel Changes",
        "Reset Participants",
        "Stop recording before using Cancel Changes",
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
        "apply as soon as you choose a dropdown option",
        "briefly stops the output stream",
        "blocked while a recording is active",
        "Python 3.11-3.14",
        "loads existing compatible playback caches",
        "startup playback is unavailable",
        "Playback panel",
        "Voice Stack panel",
        "Voice loop",
        "voice stack loop length",
        "trimming or repeating",
        "rebuilds `data/rendered/layers/voice_playback.wav`",
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
        "Graph EQ workspace tab",
        "drag point handles",
        "graph background",
        "Freq",
        "Gain",
        "Q",
        "not a musical crossfade",
        "selected timestamped stack source",
        "playback cache",
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
        "Source Library",
        "data/sources/voice/stack",
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
        "Voice loop",
        "voice_stack_raw.wav and voice_playback.wav to the selected length",
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
        "curve/background drag",
        "stale selected Voice Stack path",
        "missing selected and missing fallback",
        "Stable mode does not run the Live executor",
    ]
    for phrase in required:
        assert phrase in checklist


def test_readme_links_operator_docs() -> None:
    readme = read_text(ROOT / "README.md")

    assert "docs/operator-guide.md" in readme
    assert "docs/audio-setup-checklist.md" in readme
    assert "Start Secret Pond.command" in readme
    assert "Start Secret Pond.bat" in readme
    assert "scripts/launch_secret_pond.py" in readme
    assert "secret-pond doctor --json" in readme
    assert "secret-pond doctor --strict" in readme
    assert "secret-pond rebuild-test-library" in readme
    assert "data/sources/low/*.wav" in readme
    assert "Source Library" in readme
    assert "Restart Output" in readme
    assert "Soft" in readme
    assert "Misty" in readme
    assert "Dense" in readme
    assert "Clearer Voice" in readme
    assert "Unsaved audio changes" in readme
    assert "min/max duration" in readme
    assert "Voice loop" in readme
    assert "loop length" in readme
    assert "System" in readme
    assert "렌더 캐시" in readme
    assert "UI 상태관리 원칙" in readme
    assert "currentOperationFlags" in readme
    assert "열려 있는 드롭다운" in readme
    assert "fix: 소스 드롭다운 활성 상태 유지" in readme


def test_request_file_records_current_mvp_docs_decisions() -> None:
    request = read_text(REQUEST_FILE)
    recording_recommendations = request.split("권장값:", 1)[1].split(
        "2) 간단한 사운드 처리 기능", 1
    )[0]

    assert "- 최대 녹음 시간: 120초" in recording_recommendations
    assert "- 최대 녹음 시간: 60초" not in recording_recommendations
    assert "기존 권장값 60초가 아니라 120초" in request
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
    assert "Voice loop" in request
    assert "목소리 스택 루프 길이" in request
    assert "상태 동기화 배지" in request
    assert "오류 상태 배지" in request
    assert "Spacebar 캡처 준비 상태" in request
    assert "Hold Space to Record" in request


def test_request_file_records_phase_10_status_and_mvp_controller_boundary() -> None:
    request = read_text(REQUEST_FILE)

    assert "12) 10단계 구현 검증 상태" in request
    assert "Phase 8~10" in request
    assert "RecordingController" in request
    assert "Apply and Restart와 출력 재시작 흐름" in request
    assert "runtime.operation_lock" in request
    assert "MVP 단순성" in request


def test_lazyweb_notes_record_phase_10_verification_evidence() -> None:
    notes = read_text(ROOT / "docs" / "design" / "lazyweb-ui-notes.md")

    assert "2026-06-04 Phase 10 verification" in notes
    assert "dense status rows" in notes
    assert "DAW-style mixer" in notes
    assert "Last system.startup_playback_unavailable" in notes
    assert "text-overflow: ellipsis" in notes
    assert "bodyWidth=1440 viewportWidth=1440" in notes
    assert "bodyWidth=390 viewportWidth=390" in notes


def test_live_playback_verification_notes_record_remaining_manual_checks() -> None:
    notes = read_text(ROOT / "docs" / "design" / "lazyweb-ui-notes.md")

    assert "2026-06-06 Live playback verification notes" in notes
    assert "Remaining manual checks" in notes
    assert "physical audio output device" in notes
    assert "microphone permission prompt" in notes
    assert "exhibition speaker gain" in notes
    assert "All other Live playback acceptance checks are covered by automated tests" in notes


def test_implementation_plan_records_current_phase_10_status() -> None:
    plan = read_text(
        ROOT / "docs" / "superpowers" / "plans" / "2026-06-03-secret-pond-implementation-plan.md"
    )

    assert "2026-06-04 Phase 8~10 Status Addendum" in plan
    assert "unchecked Phase 8~10 boxes are original planning checklist items" in plan
    assert "MVP deviation" in plan
    assert "route-owned orchestration under `runtime.operation_lock`" in plan
    assert "RecordingController remains focused on recording" in plan
