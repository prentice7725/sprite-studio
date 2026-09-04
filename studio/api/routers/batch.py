# SPDX-License-Identifier: Apache-2.0
"""POST .../batches, GET .../batches/current, WS .../batches/{job_id}/events —
ENDPOINTS.md §"Sprite Mode — Batch".

`batch_service.load_queue` / `batch-queue.json` stays the persisted SSOT
(§Conventions) — this router does not track batch state of its own. The
WebSocket is a thin push transport over that same file: poll it, and only
send a frame when its content actually changed, until the batch reaches a
terminal status. Polling runs server-side so the client receives pushed
deltas over WebSocket instead of re-fetching on its own clock.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from studio.api.contracts import BatchStartRequest, BatchStartResponse, BatchStatus
from studio.api.deps import load_run_dir
from studio.backend import batch_service, run_manager

router = APIRouter(prefix="/runs/{run_id}/batches", tags=["batch"])

_POLL_SECONDS = 0.5
_TERMINAL_STATUSES = {"complete", "failed", "interrupted", "corrupt"}


@router.post("", response_model=BatchStartResponse, status_code=201)
def start_batch(run_id: str, body: BatchStartRequest) -> BatchStartResponse:
    run_dir = load_run_dir(run_id)
    try:
        job_id = batch_service.start_batch(
            run_dir, body.states, normalize=body.normalize, refine=body.refine,
            repair=body.repair, qa=body.qa,
        )
    except RuntimeError as exc:
        # "a batch is already running" — a real conflict, not a bad request.
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return BatchStartResponse(job_id=job_id)


@router.get("/current", response_model=BatchStatus)
def current_batch(run_id: str) -> BatchStatus:
    run_dir = load_run_dir(run_id)
    payload = batch_service.load_queue(run_dir)
    if payload is None:
        raise HTTPException(status_code=404, detail=f"no batch has ever run for {run_id!r}")
    return BatchStatus.model_validate(payload)


def _signature(payload: dict[str, Any]) -> str:
    """Cheap change-detection key — exact content equality, not a hash, since
    a batch payload is small (a handful of states) and correctness matters
    more than shaving bytes here."""
    return json.dumps(payload, sort_keys=True, default=str)


@router.websocket("/{job_id}/events")
async def batch_events(websocket: WebSocket, run_id: str, job_id: str) -> None:
    await websocket.accept()
    try:
        run_dir = run_manager.load_run(run_id).path
    except (ValueError, FileNotFoundError) as exc:
        await websocket.close(code=4404, reason=str(exc)[:120])
        return

    last_signature: str | None = None
    try:
        while True:
            payload = batch_service.load_queue(run_dir)
            if payload is None:
                await websocket.close(code=4404, reason=f"no batch found for {run_id!r}")
                return
            if payload.get("job_id") != job_id:
                # A different (newer, or never-matching) batch owns the queue
                # file now — this socket is watching a job that is no longer
                # the current one, not a job that is merely slow.
                await websocket.close(code=4409, reason=f"job {job_id!r} is not the current batch")
                return
            signature = _signature(payload)
            if signature != last_signature:
                await websocket.send_json(BatchStatus.model_validate(payload).model_dump())
                last_signature = signature
            if payload.get("status") in _TERMINAL_STATUSES:
                break
            await asyncio.sleep(_POLL_SECONDS)
    except WebSocketDisconnect:
        return
    await websocket.close(code=1000)
