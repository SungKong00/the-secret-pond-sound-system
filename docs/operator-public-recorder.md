# Public Voice Stack Recorder Operator Guide

> Status: runbook
> Owner: agent
> Scope: short-lived public Voice Stack collection only

## What This Deploys

This service exposes only the public Voice Stack recorder and admin stack download routes.
It does not expose the local operator dashboard or audio-device runtime.

Participant limits:

- Minimum recording: 3초
- Maximum recording: 10분
- Maximum upload: 25MB

Privacy boundary:

- 녹음 원본 파일은 저장하지 않습니다.
- Uploaded originals and decoded temporary WAV files are processing inputs only.
- Admin downloads contain accumulated Voice Stack versions and SQLite metadata, not individual voice files.

## Required Environment

Set these on Render:

- `APP_DATA_DIR=/var/data`
- `PUBLIC_RECORDING_TOKEN=<private-link-token>`
- `ADMIN_USERNAME=<admin-user>`
- `ADMIN_PASSWORD=<admin-password>`
- `PUBLIC_MAX_UPLOAD_BYTES=26214400`
- `PUBLIC_STACK_LOCK_TIMEOUT_SECONDS=30`

Render disk:

- Mount path: `/var/data`
- Size: `1 GB`
- Service plan: Starter Web Service

## Seed The Initial Stack

Before opening the participant link, copy the initial stack WAV into the deployed service data
directory and run:

```bash
uv run secret-pond public-recorder-init-seed /path/to/initial-stack.wav --root /var/data
```

This copies the seed WAV into `data/sources/voice/stack/`, mirrors it to
`data/voice/voice_stack_raw.wav`, updates `data/config/settings.json`, and records a seed
version in `data/public/stack_history.sqlite3`.

## Participant Link

Send only this private link to invited participants:

```text
https://<render-service-host>/r/<PUBLIC_RECORDING_TOKEN>
```

Users can record, discard, re-record, and then add to Voice Stack. After a submission is added,
there is no participant rollback.

## Admin Downloads

Use Basic Auth with `ADMIN_USERNAME` and `ADMIN_PASSWORD`.

List all stack versions:

```text
GET /admin/versions
```

Download latest stack:

```text
GET /admin/versions/latest/download
```

Download a historical stack:

```text
GET /admin/versions/<version_id>/download
```

## 수집 종료

After the 3 to 5 day collection window:

1. Download the latest stack and any historical versions needed from the admin endpoints.
2. Disable or delete the Render service so the public link no longer accepts recordings.
3. Keep the persistent disk until the final stack files and `stack_history.sqlite3` are backed up.
4. Rotate `PUBLIC_RECORDING_TOKEN` and `ADMIN_PASSWORD` if the service will be reused.
