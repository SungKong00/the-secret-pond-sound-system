# The Secret Pond Agent Guide

## Ouroboros Workflow

Use Ouroboros for planning or executing non-trivial changes in this repository.
This project is registered as the default Ouroboros brownfield context, so
interviews should treat the existing codebase, audio runtime, operator UI, and
docs as active constraints.

Preferred flow:

1. Start with `ooo interview "<goal>"` for unclear or broad work.
2. Generate a Seed from the interview before implementation.
3. Run the Seed with Ouroboros when the task needs multi-step execution.
4. Evaluate the result before calling the work complete.

Terminal equivalents:

```bash
ouroboros init start "<goal>"
ouroboros run workflow ~/.ouroboros/seeds/<seed>.yaml --runtime codex
ouroboros status execution <execution_id>
```

## Project Verification

Use the repository's existing Python workflow unless a task requires something
more specific:

```bash
uv run pytest
uv run ruff check .
```

For UI-visible changes, verify the rendered dashboard in addition to tests. For
audio/device changes, separate input capture format, internal processing format,
and output playback behavior before deciding whether a warning is fatal.

## Commit Style

Keep commits focused and use Korean Conventional Commit messages, for example:

```text
feat: 우로보로스 작업 흐름 추가
fix: 입력 장치 상태 표시 수정
docs: 운영자 점검 절차 정리
```
