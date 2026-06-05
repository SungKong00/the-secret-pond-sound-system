# The Secret Pond Sound System

〈비밀의 연못〉을 위한 Python 기반 녹음, 오디오 처리, 3레이어 루프 재생 시스템입니다.

## 개발 환경

macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
python -m pytest
secret-pond doctor
secret-pond serve
```

Windows PowerShell:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m pytest
secret-pond doctor
secret-pond serve
```

## 현재 구현 범위

- 프로젝트 기본 세팅, 설정/경로/상태 모델, 오디오 장치 조회
- WAV 입출력, 오디오 버퍼 변환, 오프라인 녹음 처리 체인
- 목소리 스택 누적:
  - `live_ephemeral`: 실제 운영 모드. 개별 단일 목소리 WAV를 남기지 않고 합본에만 반영
  - `test_library`: 테스트/리허설 모드. `data/processed/accepted/*.wav`와 manifest를 남겨 재빌드 가능
- `low`, `mid`, `voice` 3레이어 렌더링과 staged EQ/필터 적용
- 단일 출력 엔진용 레이어 믹서와 `sounddevice` 출력 스트림 래퍼
- 녹음 컨트롤러, 최대 120초 자동 정지, 참여자 카운터, JSONL 운영 이벤트 로그
- FastAPI 기반 로컬 API와 운영자 웹 대시보드, System 패널 입력/출력 장치 즉시 변경 UI
- Source Library 파일 관리: `data/sources/low/*.wav`, `data/sources/mid/*.wav`,
  `data/sources/voice/raw/*.wav`, `data/sources/voice/stack/*.wav` 조회/선택/추가/삭제
- 대시보드 System 패널: 준비 음원 파일 상태, 선택된 입출력 장치, 최근 JSONL 이벤트 요약
- `secret-pond rebuild-test-library`: 리허설용 accepted WAV와 manifest에서 목소리 스택과 voice playback 캐시 재생성
- WebSocket 기반 상태 push와 연결 종료 시 활성 녹음 정지
- 앱 시작 시 기존 렌더 캐시를 활성 오디오 설정과 대조해 재생기에 로드하고, 캐시가 없거나 맞지 않으면 준비 음원에서 렌더를 다시 시도
- 출력 중 staged 설정을 적용할 때 렌더/플레이어/출력을 롤백 가능한 순서로 재시작
- 운영자 UI 상태 보강: `Unsaved audio changes`, 레이어 Active/Pending Change, 녹음 min/max duration, `Restart Output`, Voice Stack panel
- Voice Stack panel의 `Voice loop` 변경 예정값 조절: 목소리 스택 loop length를 바꾸고 `Apply and Restart`로 voice stack raw와 voice playback을 다시 맞춤
- Voice Treatment 프리셋: Soft, Misty, Dense, Clearer Voice

아직 구현하지 않은 범위:

- 하드웨어 버튼/터치 센서/시리얼 연동
- 실시간 EQ. 현재 EQ 슬라이더는 변경 예정값으로 저장한 뒤 `Apply and Restart`로 적용

## 운영 순서

자세한 운영 절차는 `docs/operator-guide.md`, 점검 목록은 `docs/audio-setup-checklist.md`를 확인합니다.

1. `data/sources/low/*.wav`, `data/sources/mid/*.wav`에 사용할 WAV를 넣거나,
   기존 호환 경로인 `data/sources/low.wav`, `data/sources/mid.wav`를 준비합니다.
2. `secret-pond doctor`로 장치와 의존성을 확인합니다. 로그용 JSON이 필요하면 `secret-pond doctor --json`을 사용하고, 준비 음원이 배치된 뒤에는 `secret-pond doctor --strict`를 현장 준비 상태 게이트로 사용할 수 있습니다.
3. `secret-pond serve`를 실행하고 `http://127.0.0.1:8000`을 엽니다.
4. System 패널에서 선택된 소스 상태를 확인하고, 입력/출력 장치 드롭다운과 Source Library에서 사용할 파일을 고릅니다.
5. 시작 시 렌더 캐시가 활성 오디오 설정과 맞으면 자동으로 player에 로드됩니다. 캐시가 없거나 맞지 않으면 준비 음원에서 자동 렌더를 시도하며, 실패 원인은 System 패널의 최근 이벤트에서 확인합니다.
6. `Start Output`을 눌러 실제 출력 스트림을 시작합니다.
7. Loop Mixer와 Voice Stack panel의 EQ/볼륨 또는 `Voice loop`를 바꾼 뒤에는 `Apply and Restart`로 새 렌더를 만들고 player에 다시 로드합니다.
8. 필요하면 `Restart Output`으로 현재 로드된 재생을 처음부터 다시 시작합니다.
9. `Arm` 후 스페이스바를 누르고 있는 동안 녹음합니다.

리허설에서 `test_library` 모드의 `data/processed/accepted/*.wav`와
`data/voice/voice_stack_manifest.json`를 기준으로 스택을 다시 만들 때는 앱을 멈춘 뒤
`secret-pond rebuild-test-library --root .`를 실행합니다. 이 명령은 활성 시작 설정이
`test_library`일 때만 `voice_stack_raw.wav`와 `voice_playback.wav`를 다시 만듭니다.

현재 MVP 제약:

- 출력 중 `Apply and Restart`를 누르면 출력 스트림을 잠시 멈추고 새 렌더를 검증한 뒤 다시 시작합니다. 적용 실패 시 가능한 범위에서 이전 렌더/플레이어/출력을 복원합니다.
- 입력/출력 장치는 System 패널 드롭다운에서 바꾸는 즉시 적용됩니다. 출력 중 출력 장치를 바꾸면 출력 스트림을 잠시 멈췄다가 새 장치로 다시 시작하고, 녹음 중 입력 장치 변경은 차단됩니다.
- `sample_rate`, `channels` 변경은 현재 UI Apply로 처리하지 않습니다. 이 값은 앱을 재시작해 활성 시작 설정으로 맞춰야 합니다.
- Source Library 선택값이 있으면 선택된 WAV를 사용하고, 선택값이 없으면 기존
  `data/sources/low.wav`, `data/sources/mid.wav`, `data/voice/voice_stack_raw.wav`를
  legacy fallback으로 사용합니다.
- Accepted recordings create timestamped voice raw and stack WAV files under
  `data/sources/voice/raw/` and `data/sources/voice/stack/`.
- 준비 음원 파일이 없으면 시작 시 자동 렌더와 `Apply and Restart`가 실패합니다. 기존 활성 설정과 맞는 렌더 캐시가 있으면 그 캐시는 계속 로드할 수 있습니다.

## UI 상태관리 원칙

- 대시보드 작업중 상태는 `sourceMutationInFlight`, `applyInFlight`, `deviceChangeInFlight` 같은 개별 플래그를 직접 흩뿌리지 않고 `currentOperationFlags()`와 순수 상태 도출 함수에 모아서 전달합니다.
- 버튼, 드롭다운, 업로드, 삭제 같은 명령 핸들러는 화면의 disabled 상태만 믿지 않고 실행 직전에 다시 잠금 상태를 확인합니다.
- 열려 있는 드롭다운은 옵션 목록을 다시 만들거나 활성 컨트롤을 불필요하게 disabled로 바꾸지 않습니다. 대신 렌더를 지연하고, 명령 실행 경계에서 잠금을 확인합니다.
- 새 작업중 상태를 추가할 때는 `operationFlagKeys`, `deriveOperationLocks`, 관련 render signature, 정적 UI 테스트를 함께 갱신합니다.
- 실시간 EQ는 아직 구현하지 않습니다. 현재 구조에서는 슬라이더 변경을 draft에 모으고 `Apply and Restart`에서 렌더를 교체하며, 나중에 실시간 적용이 필요하면 pure state derivation과 오디오 엔진 경계를 유지한 채 별도 적용 경로를 추가합니다.

## 커밋 규칙

커밋 메시지는 Conventional Commits 형식을 쓰되, 설명은 한글로 작성합니다.
작업 단위는 작게 유지하고, 관련 테스트/문서만 함께 묶습니다.

```text
feat: 프로젝트 기본 세팅
fix: 소스 드롭다운 활성 상태 유지
refactor: 작업 상태 플래그 전달 정리
docs: 운영자 안내 문서 추가
```

## 준비 음원 위치

```text
data/sources/low.wav
data/sources/mid.wav
```

권장 라이브러리 위치:

```text
data/sources/low/*.wav
data/sources/mid/*.wav
data/sources/voice/raw/*.wav
data/sources/voice/stack/*.wav
```

런타임 생성 파일은 `data/` 아래에 저장되며 대부분 `.gitignore`로 제외됩니다.
