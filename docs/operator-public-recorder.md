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
- Public uploads pass through 러프 음량 보정 before they are added to the stack. The
  guard uses RMS to leave normal recordings unchanged, boost only very quiet takes, attenuate
  very loud takes, and keep the final peak under the safety ceiling.

## Render 배포 체크리스트

Deploy this service as a short-lived Render Web Service.

1. Create the service from the repository Blueprint using `render.yaml`, or create a
   Docker Web Service manually with `Dockerfile.public-recorder`.
2. Confirm the service uses Docker runtime, exposes port `${PORT:-8000}`, and starts with
   `uvicorn secret_pond.public_app:create_public_app --factory --host 0.0.0.0`.
3. Keep `autoDeploy: false` for the collection window so production changes are intentional.
4. Attach a Persistent Disk named `secret-pond-public-data` at `/var/data` with `sizeGB: 1`.
   This disk stores the accumulated Voice Stack versions and `stack_history.sqlite3`.
5. Set `APP_DATA_DIR=/var/data` so all public-recorder data is written to the Persistent Disk.
6. Enter all secret values in Render environment variables. Do not commit real
   `PUBLIC_RECORDING_TOKEN`, `ADMIN_USERNAME`, or `ADMIN_PASSWORD` values.
7. After the service is live, run the seed initialization command before sending the
   participant link.
8. Verify the admin list and latest download endpoints with Basic Auth.

## Render Environment Values

Set these on Render:

| Key | Render value | Note |
| --- | --- | --- |
| `APP_DATA_DIR` | `/var/data` | Public recorder data root on the Persistent Disk. |
| `PUBLIC_RECORDING_TOKEN` | `<32+ char URL-safe random token>` | Private participant link token used in `/r/<PUBLIC_RECORDING_TOKEN>`. |
| `ADMIN_USERNAME` | `<admin-only username>` | Basic Auth username for stack history and downloads. |
| `ADMIN_PASSWORD` | `<long random password>` | Basic Auth password. Use a generated password, not a reused one. |
| `PUBLIC_MAX_UPLOAD_BYTES` | `26214400` | 25MB upload limit. |
| `PUBLIC_STACK_LOCK_TIMEOUT_SECONDS` | `30` | Wait up to 30 seconds for the stack update lock. |

Copyable non-secret defaults:

```bash
APP_DATA_DIR=/var/data
PUBLIC_MAX_UPLOAD_BYTES=26214400
PUBLIC_STACK_LOCK_TIMEOUT_SECONDS=30
```

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

Step-by-step:

1. Deploy the Render service and confirm it reaches the public health path or recorder page.
2. Open a Render shell for the service, or otherwise place the initial stack WAV where the
   service can read it.
3. Run `uv run secret-pond public-recorder-init-seed /path/to/initial-stack.wav --root /var/data`.
4. Confirm `/admin/versions` shows the seed version when requested with Basic Auth.
5. Download `/admin/versions/latest/download` and confirm the file plays as the initial stack.
6. Only then send the participant link.

## Participant Link

Send only this private link to invited participants:

```text
https://<render-service-host>/r/<PUBLIC_RECORDING_TOKEN>
```

Users can record, discard, re-record, and then add to Voice Stack. After a submission is added,
there is no participant rollback.

## Admin Downloads

Use Basic Auth with `ADMIN_USERNAME` and `ADMIN_PASSWORD`.

Open the admin page:

```text
GET /admin
```

The `/admin` page lists accumulated Voice Stack versions. It shows submission metadata,
created time, duration, file size, added chunk count, level guard gain, 미리듣기 controls,
download buttons, and a simple 삭제 button.

Admin stack upload:

- Use the `Upload Voice Stack` control on `/admin` to upload a WAV stack.
- Uploaded admin stacks are stored as accumulated Voice Stack versions, not participant
  source recordings.
- The uploaded WAV becomes the 새 최신 누적 스택 immediately.
- The server mirrors the uploaded WAV to `data/voice/voice_stack_raw.wav`, updates active
  and draft `voice_stack_path`, and records the history row as `kind=upload`.
- The next public recording stacks onto that uploaded version.
- Only Basic Auth admins can upload or download stack versions.

Upload a stack version through the API:

```text
POST /admin/versions/upload
```

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

Preview a historical stack:

```text
GET /admin/versions/<version_id>/preview
```

Delete a stack version:

```text
DELETE /admin/versions/<version_id>
```

Deletion behavior:

- The accumulated stack WAV file for that version is deleted.
- The SQLite history row remains with `deleted_at` so the admin can still see that it existed.
- Deleted versions cannot be used for 미리듣기 or download.
- If the latest version is deleted, the next public recording stacks onto the 삭제되지 않은 최신
  version.
- If every version is deleted, seed the initial stack again before reopening collection.

Rough level guard:

- The guard checks RMS after normal recording processing and before adding to Voice Stack.
- RMS below `-32 dBFS` is treated as too quiet and is boosted toward `-28 dBFS`, capped at
  `+9 dB`.
- RMS from `-32 dBFS` through `-18 dBFS` is treated as normal and is not changed.
- RMS above `-18 dBFS` is treated as too loud and is attenuated toward `-21 dBFS`.
- Final peak is capped at `0.80` to avoid unexpectedly hot uploads.
- This is intentionally coarse normalization, not exact LUFS matching.

Admin download verification:

1. Visit `https://<render-service-host>/admin/versions`.
2. Enter `ADMIN_USERNAME` and `ADMIN_PASSWORD` in the Basic Auth prompt.
3. Confirm the JSON includes the seed version and any later participant versions.
4. Visit `https://<render-service-host>/admin/versions/latest/download`.
5. Confirm the downloaded WAV is the latest accumulated Voice Stack, not an individual
   participant recording.
6. Visit `https://<render-service-host>/admin` and confirm preview, download, and delete
   controls render.

## Post-Deploy Mobile Checklist

Run this checklist once on iOS Safari and once on Android Chrome before sharing the link
widely.

1. Open `https://<render-service-host>/r/<PUBLIC_RECORDING_TOKEN>`.
2. Confirm the page explains the 3초 minimum, 10분 maximum, 25MB limit, and that
   녹음 원본 파일은 저장하지 않습니다.
3. Start recording and approve the 마이크 권한 prompt.
4. Confirm 3초 전에는 녹음 중지 button stays disabled.
5. After 3초, stop recording and confirm the page allows re-record or Voice Stack에 추가.
6. Re-record once and discard the previous attempt.
7. Submit once with Voice Stack에 추가 and confirm the success state appears.
8. Confirm a second browser or device can submit after the first one without losing the
   latest stack version.
9. Download `/admin/versions/latest/download` and confirm the latest accumulated stack changed.
10. Confirm no route or admin screen exposes the participant's standalone source recording.

## 수집 종료

After the 3 to 5 day collection window:

1. Download the latest stack and any historical versions needed from the admin endpoints.
2. Disable or delete the Render service so the public link no longer accepts recordings.
3. Keep the persistent disk until the final stack files and `stack_history.sqlite3` are backed up.
4. Rotate `PUBLIC_RECORDING_TOKEN` and `ADMIN_PASSWORD` if the service will be reused.
