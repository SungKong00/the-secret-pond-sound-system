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
- FastAPI 기반 로컬 API와 운영자 웹 대시보드

아직 구현하지 않은 범위:

- WebSocket 기반 실시간 상태 push
- 하드웨어 버튼/터치 센서/시리얼 연동
- 출력 중 안전한 Apply-and-Restart 재시작
- 실시간 EQ. 현재 EQ 슬라이더는 초안으로 저장한 뒤 `Apply and Restart`로 적용

## 운영 순서

1. `data/sources/low.wav`, `data/sources/mid.wav`를 준비합니다.
2. `secret-pond doctor`로 장치와 의존성을 확인합니다.
3. `secret-pond serve`를 실행하고 `http://127.0.0.1:8000`을 엽니다.
4. 웹 대시보드에서 필요한 EQ/볼륨을 조정합니다.
5. `Apply and Restart`를 눌러 3개 레이어 렌더를 생성하고 player에 로드합니다.
6. `Start Output`을 눌러 실제 출력 스트림을 시작합니다.
7. `Arm` 후 스페이스바를 누르고 있는 동안 녹음합니다.

현재 MVP 제약:

- 출력 중에는 `Apply and Restart`가 막힙니다. 먼저 `Stop Output`을 누른 뒤 적용하세요.
- `sample_rate`, `channels`, `output_device_id` 변경은 현재 UI Apply로 처리하지 않습니다. 설정 파일을 바꾼 뒤 앱을 재시작하는 방식으로 다룹니다.
- 준비 음원 파일이 없으면 `Apply and Restart`가 실패합니다.

## 커밋 규칙

커밋 메시지는 Conventional Commits 형식을 쓰되, 설명은 한글로 작성합니다.
현재 프로젝트에서는 타입과 설명 사이를 콜론이 아니라 세미콜론으로 구분합니다.

```text
feat;프로젝트 기본 세팅
feat;설정과 상태 모델 추가
fix;오디오 버퍼 채널 계산 수정
docs;운영자 안내 문서 추가
```

## 준비 음원 위치

```text
data/sources/low.wav
data/sources/mid.wav
```

런타임 생성 파일은 `data/` 아래에 저장되며 대부분 `.gitignore`로 제외됩니다.
