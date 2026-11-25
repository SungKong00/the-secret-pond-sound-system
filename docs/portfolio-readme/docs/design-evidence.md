# 설계 근거

- **Stable / Live:** 원본 `docs/superpowers/plans/2026-06-08-live-stable-apply-state-refactor.md`, `services/settings_apply.py`, `services/live_graph_eq.py`, `audio/renderer.py`. Stable 시연은 EQ 상태 검증 기록에 있다. Live에서 1초는 입력 합치기 정책값이다.
- **그래프:** 원본 `docs/superpowers/plans/2026-06-13-secret-pond-dsssp-graph-eq.md`, `e422dd9`(대시보드 연결), `e8314fe`(셸프 및 벨 포인트 조작). `web/frontend/graph_eq_dsssp_adapter.mjs`가 그래프 값 변환을 담당한다. 2026-06-13 프로젝트 대화에서 운영자에게 적절한 조작과 양끝 셸프·추가 벨 포인트의 동작을 검토한 요구도 대조했다.
- **녹음 보관:** 원본 `docs/operator-guide.md`, `services/storage_mode.py`, `services/recording_workflow.py`, `tests/services/test_controller.py`. 시연의 입력은 하나의 정해진 로컬 파형이고, 원본 파일 보관 여부와 실제 스택 생성을 별도로 확인했다.
- **동기화된 루프:** `2a2ec02`(정규화 루프 전환), `78b767f`(재생 위치 동기화), `services/loop_cycle.py`, `audio/player.py`. 2026-06-08 프로젝트 대화에서 지정한 공통 루프 길이, 부족한 부분의 반복, 시작 무페이드와 경계에서만 겹치는 전환을 확인했다.
