# The Secret Pond Sound System

〈비밀의 연못〉을 위한 Python 기반 녹음, 오디오 처리, 3레이어 루프 재생 시스템입니다.

## 프로토타입 실행

의뢰자에게 전달할 때는 터미널 명령 대신 OS별 실행 파일을 사용합니다.

macOS:

1. Python 3.11-3.14가 설치되어 있는지 확인합니다.
2. `Start Secret Pond.command`를 더블클릭합니다.
3. 첫 실행이면 `.venv`를 만들고 필요한 패키지를 설치한 뒤 서버를 켭니다.
4. 브라우저가 자동으로 열리지 않으면 `http://127.0.0.1:8000`을 직접 엽니다.

Windows:

1. Python 3.11-3.14가 설치되어 있는지 확인합니다.
2. `Start Secret Pond.bat`를 더블클릭합니다.
3. 첫 실행이면 `.venv`를 만들고 필요한 패키지를 설치한 뒤 서버를 켭니다.
4. 브라우저가 자동으로 열리지 않으면 `http://127.0.0.1:8000`을 직접 엽니다.

두 실행 파일은 공통 bootstrapper인 `scripts/launch_secret_pond.py`를 호출합니다.
이 창을 닫거나 `Ctrl+C`를 누르면 서버가 종료됩니다. 의존성을 다시 설치해야 할 때는
`scripts/launch_secret_pond.py --reinstall`을 사용합니다.

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
  - `live_ephemeral`: 실제 운영 모드. 일반 녹음은 Voice Stack을 직접 갱신하고 timestamped Voice Stack source와 legacy mirror를 남기되, 개별 Voice Raw나 test-library 재빌드용 accepted chunk/manifest는 만들지 않음
  - `test_library`: 테스트/리허설 모드. 일반 녹음은 timestamped Voice Raw source로 저장하고, 그 Voice Raw를 스택에 추가할 때 `data/processed/accepted/*.wav`와 manifest를 남겨 재빌드 가능
- `low`, `mid`, `voice` 3레이어 렌더링과 Live/Stable EQ·필터 적용
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
- 운영자 UI 상태 보강: `저장 안 된 오디오 변경`, 레이어 Active/Pending Change, 녹음 min/max duration, `다시 재생`, Voice Stack panel
- Voice Stack panel의 `Voice loop` 변경 예정값 조절: 목소리 스택 loop length를 바꾸고 `Apply and Restart`로 voice stack raw와 voice playback을 다시 맞춤
- Voice Treatment 프리셋: Soft, Misty, Dense, Clearer Voice

아직 구현하지 않은 범위:

- 하드웨어 버튼/터치 센서/시리얼 연동

## 운영 순서

자세한 운영 절차는 `docs/operator-guide.md`, 점검 목록은 `docs/audio-setup-checklist.md`를 확인합니다.

1. `data/sources/low/*.wav`, `data/sources/mid/*.wav`에 사용할 WAV를 넣거나,
   기존 호환 경로인 `data/sources/low.wav`, `data/sources/mid.wav`를 준비합니다.
2. `secret-pond doctor`로 장치와 의존성을 확인합니다. 로그용 JSON이 필요하면 `secret-pond doctor --json`을 사용하고, 준비 음원이 배치된 뒤에는 `secret-pond doctor --strict`를 현장 준비 상태 게이트로 사용할 수 있습니다.
3. 전달용 프로토타입은 `Start Secret Pond.command` 또는 `Start Secret Pond.bat`를 실행합니다. 개발 중에는 `secret-pond serve`를 실행하고 `http://127.0.0.1:8000`을 엽니다.
4. System 패널에서 선택된 소스 상태를 확인하고, 입력/출력 장치 드롭다운과 Source Library에서 사용할 파일을 고릅니다.
5. 시작 시 렌더 캐시가 활성 오디오 설정과 맞으면 자동으로 player에 로드됩니다. 캐시가 없거나 맞지 않으면 준비 음원에서 자동 렌더를 시도하며, 실패 원인은 System 패널의 최근 이벤트에서 확인합니다.
6. `재생`을 눌러 실제 출력 스트림을 시작합니다.
7. Live 모드에서는 볼륨/음소거/위치 이동/EQ/Filter Range가 즉시 저장되고, Graph EQ·Filter Range는 debounce 뒤 최신 값만 렌더링됩니다. Stable 모드나 fallback이 필요하면 `Apply and Restart`로 새 렌더를 만들고 player에 다시 로드합니다.
8. 필요하면 `다시 재생`으로 현재 로드된 재생을 처음부터 다시 시작합니다.
9. `녹음 준비`를 켠 뒤 스페이스바를 누르고 있는 동안 녹음합니다.

리허설에서 `test_library` 모드의 `data/processed/accepted/*.wav`와
`data/voice/voice_stack_manifest.json`를 기준으로 스택을 다시 만들 때는 앱을 멈춘 뒤
`secret-pond rebuild-test-library --root .`를 실행합니다. 이 명령은 활성 시작 설정이
`test_library`일 때만 `voice_stack_raw.wav`와 `voice_playback.wav`를 다시 만듭니다.

현재 MVP 제약:

- 운영자 대시보드는 현장 노트북/데스크톱 브라우저 기준입니다. 모바일 폭 화면은 전시 운영 지원 범위가 아니며, EQ 조정과 녹음/재생 운영은 충분한 가로폭이 있는 브라우저에서 진행합니다.
- 출력 중 `Apply and Restart`를 누르면 출력 스트림을 잠시 멈추고 새 렌더를 검증한 뒤 다시 시작합니다. 적용 실패 시 가능한 범위에서 이전 렌더/플레이어/출력을 복원합니다.
- 입력/출력 장치는 System 패널 드롭다운에서 바꾸는 즉시 적용됩니다. 출력 중 출력 장치를 바꾸면 출력 스트림을 잠시 멈췄다가 새 장치로 다시 시작하고, 녹음 중 입력 장치 변경은 차단됩니다.
- `sample_rate`, `channels` 변경은 현재 UI Apply로 처리하지 않습니다. 이 값은 앱을 재시작해 활성 시작 설정으로 맞춰야 합니다.
- Source Library 선택값이 있으면 선택된 WAV를 사용하고, 선택값이 없으면 기존
  `data/sources/low.wav`, `data/sources/mid.wav`, `data/voice/voice_stack_raw.wav`를
  legacy fallback으로 사용합니다.
- 녹음이 accepted되면 현재 Voice Stack 모드에 맞는 source가 남습니다.
  `test_library`에서는 `data/sources/voice/raw/` 아래 Voice Raw가 저장되고,
  `live_ephemeral`에서는 `data/sources/voice/stack/` 아래 Voice Stack source가 저장됩니다.
- 준비 음원 파일이 없으면 시작 시 자동 렌더와 `Apply and Restart`가 실패합니다. 기존 활성 설정과 맞는 렌더 캐시가 있으면 그 캐시는 계속 로드할 수 있습니다.

## UI 상태관리 원칙

- 대시보드 작업중 상태는 `sourceMutationInFlight`, `applyInFlight`, `deviceChangeInFlight` 같은 개별 플래그를 직접 흩뿌리지 않고 `currentOperationFlags()`와 순수 상태 도출 함수에 모아서 전달합니다.
- 버튼, 드롭다운, 업로드, 삭제 같은 명령 핸들러는 화면의 disabled 상태만 믿지 않고 실행 직전에 다시 잠금 상태를 확인합니다.
- 열려 있는 드롭다운은 옵션 목록을 다시 만들거나 활성 컨트롤을 불필요하게 disabled로 바꾸지 않습니다. 대신 렌더를 지연하고, 명령 실행 경계에서 잠금을 확인합니다.
- 새 작업중 상태를 추가할 때는 `operationFlagKeys`, `deriveOperationLocks`, 관련 render signature, 정적 UI 테스트를 함께 갱신합니다.
- Live 모드의 EQ/Filter Range 변경은 draft에 먼저 저장한 뒤 server-owned render request로 처리합니다. 빠른 연속 조작에서는 stale request를 버리고 마지막 값만 audible buffer로 승격합니다. Stable 모드는 기존처럼 `Apply and Restart`에서 렌더를 교체합니다.

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
