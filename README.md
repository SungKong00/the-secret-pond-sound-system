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

- Phase 0: 프로젝트 기본 세팅
- Phase 1: 설정, 경로, 상태, 오디오 장치 모델
- Phase 2: 오디오 버퍼와 WAV 파일 입출력

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
