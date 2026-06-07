# Live/Stable Apply State Refactor

## Goal

Refactor the Live/Stable settings application flow so runtime changes, staged Stable changes, per-card feedback, rollback, and playback timeline synchronization are deterministic and easier to maintain.

## Task Units

1. Add a reusable Live apply feedback state model.
   - Test pending/applying/applied/failed/stale transitions.
   - Test stale responses are ignored by request id and mode epoch.
   - Commit: `feat: 라이브 적용 상태 모델 추가`

2. Wire Live UI feedback through the state model.
   - Keep Live card highlight and spinner only while the latest request is active.
   - Roll back failed Live changes to confirmed values and show the Korean caution banner.
   - Commit: `feat: 라이브 적용 피드백 정리`

3. Separate Live and Stable mode transitions.
   - Preserve Stable Apply and Restart behavior.
   - Ensure Live->Stable and Stable->Live do not mix pending request state or staged drafts.
   - Commit: `feat: 적용 모드 전환 상태 분리`

4. Verify playback transition and timeline synchronization.
   - Confirm Low/Mid/Voice transition coverage.
   - Confirm seek/progress follows the actual playback cursor.
   - Commit: `feat: 재생 진행 동기화 검증 강화`

## Verification

- Run focused web/audio tests after each task unit.
- Run `uv run pytest` and `uv run ruff check .` before final completion.
- For UI-visible changes, check the rendered dashboard after code-level tests pass.
