from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket
from starlette.websockets import WebSocketDisconnect

from secret_pond.services.runtime import SecretPondRuntime
from secret_pond.web.state import state_payload

STATE_PUSH_INTERVAL_SECONDS = 0.5

router = APIRouter()


@router.websocket("/ws/state")
async def state_socket(websocket: WebSocket) -> None:
    runtime = _runtime(websocket)
    if runtime is None:
        await websocket.close(code=1011, reason="runtime is not ready")
        return

    await websocket.accept()
    try:
        while True:
            await _poll_auto_stop_best_effort(runtime)
            payload = await asyncio.to_thread(_locked_state_payload, runtime)
            await websocket.send_json(payload)
            try:
                await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=STATE_PUSH_INTERVAL_SECONDS,
                )
            except TimeoutError:
                continue
    except WebSocketDisconnect:
        await _stop_recording_if_active(runtime)


def _runtime(websocket: WebSocket) -> SecretPondRuntime | None:
    return getattr(websocket.app.state, "runtime", None)


async def _poll_auto_stop_best_effort(runtime: SecretPondRuntime) -> None:
    await asyncio.to_thread(_locked_poll_auto_stop_best_effort, runtime)


def _locked_poll_auto_stop_best_effort(runtime: SecretPondRuntime) -> None:
    try:
        with runtime.operation_lock:
            runtime.controller.poll_auto_stop()
    except RuntimeError:
        return


async def _stop_recording_if_active(runtime: SecretPondRuntime) -> None:
    await asyncio.to_thread(_locked_stop_recording_if_active, runtime)


def _locked_stop_recording_if_active(runtime: SecretPondRuntime) -> None:
    try:
        with runtime.operation_lock:
            if not runtime.controller.is_recording:
                return
            runtime.controller.stop_recording()
    except RuntimeError:
        return


def _locked_state_payload(runtime: SecretPondRuntime) -> dict:
    with runtime.operation_lock:
        return state_payload(runtime)
