# Public Recorder Admin History And Level Guard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Basic Auth admin history page with preview/download/delete controls and apply coarse upload level correction before public Voice Stack commits.

**Architecture:** Extend the existing public FastAPI app and static assets only. Keep individual participant recordings ephemeral, keep stack history records in SQLite, mark deleted stack versions with tombstones, and make the latest active version mean the newest non-deleted stack version.

**Tech Stack:** FastAPI, SQLite, static HTML/CSS/JS, NumPy audio buffers, existing Secret Pond WAV/Voice Stack services.

---

### Task 1: Stack History Deletion Semantics

**Files:**
- Modify: `src/secret_pond/services/public_stack_history.py`
- Modify: `src/secret_pond/services/public_voice_stack.py`
- Test: `tests/services/test_public_stack_history.py`
- Test: `tests/services/test_public_voice_stack.py`

- [ ] Add failing tests for `deleted_at`, `latest()` skipping deleted records, and commits using the latest non-deleted parent.
- [ ] Implement schema migration with nullable `deleted_at`.
- [ ] Add `mark_deleted(record_id, deleted_at)` and make `latest()` filter deleted versions.
- [ ] Update public commit parent selection to call `latest()` once and use that non-deleted record.
- [ ] Run targeted service tests and commit.

### Task 2: Admin History Page And Version File Actions

**Files:**
- Create: `src/secret_pond/web/static/public_admin.html`
- Create: `src/secret_pond/web/static/public_admin.css`
- Create: `src/secret_pond/web/static/public_admin.js`
- Modify: `src/secret_pond/public_app.py`
- Test: `tests/web/test_public_recorder_routes.py`
- Test: `tests/web/test_public_admin_static.py`
- Test: `tests/test_public_recorder_deployment.py`

- [ ] Add failing route tests for `/admin`, `/admin/versions/{id}/preview`, and `DELETE /admin/versions/{id}`.
- [ ] Add failing static tests for rendering version rows, audio preview, download button, deleted state, and confirm-before-delete.
- [ ] Implement the Basic Auth `/admin` page route and static assets.
- [ ] Implement preview and delete endpoints. Delete removes the WAV file, marks the DB row deleted, and blocks later preview/download for that version.
- [ ] Run targeted web tests and commit.

### Task 3: Coarse Public Recording Level Guard

**Files:**
- Modify: `src/secret_pond/services/public_settings.py`
- Modify: `src/secret_pond/services/public_voice_stack.py`
- Modify: `src/secret_pond/services/public_stack_history.py`
- Test: `tests/services/test_public_voice_stack.py`
- Test: `tests/services/test_public_stack_history.py`

- [ ] Add failing tests showing quiet uploads are boosted, loud uploads are attenuated, normal uploads are unchanged, and final peak is capped.
- [ ] Implement RMS dBFS measurement and coarse gain selection: quiet below `-32 dBFS` targets `-28 dBFS` with max `+9 dB`; loud above `-18 dBFS` targets `-21 dBFS`; normal range is unchanged; final peak cap is `0.80`.
- [ ] Record `level_guard_gain_db`, `level_guard_rms_dbfs`, and `level_guard_peak_after` in stack history metadata.
- [ ] Run targeted audio/service tests and commit.

### Task 4: Operator Docs And Verification

**Files:**
- Modify: `docs/operator-public-recorder.md`
- Test: `tests/test_public_recorder_deployment.py`

- [ ] Document `/admin`, preview, delete, latest non-deleted behavior, and coarse level guard.
- [ ] Run `uv run pytest` and `uv run ruff check .`.
- [ ] Push `codex/public-voice-stack-recorder` so Render can redeploy.
