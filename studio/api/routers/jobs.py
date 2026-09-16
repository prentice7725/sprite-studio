# SPDX-License-Identifier: Apache-2.0
"""HTTP and WebSocket transport for single-operation background jobs."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from studio.api.contracts import JobListResponse, JobStartRequest, JobStartResponse, JobStatusResponse
from studio.api.deps import asset_url, load_run_and_request, load_run_dir, require_state
from studio.backend import job_service


router = APIRouter(prefix="/runs/{run_id}/jobs", tags=["jobs"])
_POLL_SECONDS = 0.25
_TERMINAL = {"succeeded", "failed", "cancelled", "interrupted"}


def _public_result(run_id: str, run_dir, result: dict[str, Any] | None) -> dict[str, Any] | None:
    if result is None:
        return None
    result = dict(result)
    path_keys = {
        "raw_asset_path": "raw_asset",
        "output_asset_path": "output_asset",
        "refined_preview_asset_path": "refined_preview_asset",
        "sprite_sheet_asset_path": "sprite_sheet_asset",
        "manifest_asset_path": "manifest_asset",
        "atlas_asset_path": "atlas_asset",
        "motion_plan_asset_path": "motion_plan_asset",
    }
    for source, target in path_keys.items():
        value = result.pop(source, None)
        if value:
            result[target] = asset_url(run_id, run_dir, run_dir / str(value))
    refs = result.pop("refs_paths", None)
    if refs is not None:
        result["refs"] = [asset_url(run_id, run_dir, run_dir / str(path)) for path in refs]
    outputs = result.pop("output_files_paths", None)
    if outputs is not None:
        result["output_files"] = [asset_url(run_id, run_dir, run_dir / str(path)) for path in outputs]
    return result


def _public(run_id: str, run_dir, payload: dict[str, Any]) -> JobStatusResponse:
    data = dict(payload)
    data["result"] = _public_result(run_id, run_dir, data.get("result"))
    return JobStatusResponse.model_validate(data)


def _load(run_id: str, job_id: str):
    run_dir = load_run_dir(run_id)
    payload = job_service.load_job(run_dir, job_id)
    if payload is None:
        raise HTTPException(status_code=404, detail=f"job not found: {job_id!r}")
    return run_dir, payload


@router.post("", response_model=JobStartResponse, status_code=202)
def start_job(run_id: str, body: JobStartRequest) -> JobStartResponse:
    run_dir, request = load_run_and_request(run_id)
    if body.state is not None:
        require_state(request, body.state)
    if body.operation not in {"export_compose", "export_runtime"} and body.state is None:
        raise HTTPException(status_code=400, detail=f"operation {body.operation!r} requires a state")
    try:
        job_id = job_service.start_job(
            run_dir,
            body.operation,
            state=body.state,
            options=body.options,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JobStartResponse(job_id=job_id)


@router.get("", response_model=JobListResponse)
def list_jobs(run_id: str) -> JobListResponse:
    run_dir = load_run_dir(run_id)
    return JobListResponse(jobs=[_public(run_id, run_dir, item) for item in job_service.list_jobs(run_dir)])


@router.get("/{job_id}", response_model=JobStatusResponse)
def get_job(run_id: str, job_id: str) -> JobStatusResponse:
    run_dir, payload = _load(run_id, job_id)
    return _public(run_id, run_dir, payload)


@router.post("/{job_id}/cancel", response_model=JobStatusResponse)
def cancel_job(run_id: str, job_id: str) -> JobStatusResponse:
    run_dir = load_run_dir(run_id)
    try:
        payload = job_service.cancel_job(run_dir, job_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _public(run_id, run_dir, payload)


@router.post("/{job_id}/retry", response_model=JobStartResponse, status_code=202)
def retry_job(run_id: str, job_id: str) -> JobStartResponse:
    run_dir = load_run_dir(run_id)
    try:
        next_job_id = job_service.retry_job(run_dir, job_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409 if isinstance(exc, RuntimeError) else 400, detail=str(exc)) from exc
    return JobStartResponse(job_id=next_job_id)


def _signature(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, default=str)


@router.websocket("/{job_id}/events")
async def job_events(websocket: WebSocket, run_id: str, job_id: str) -> None:
    await websocket.accept()
    try:
        run_dir = load_run_dir(run_id)
    except HTTPException as exc:
        await websocket.close(code=4404, reason=str(exc.detail)[:120])
        return

    last_signature: str | None = None
    try:
        while True:
            payload = job_service.load_job(run_dir, job_id)
            if payload is None:
                await websocket.close(code=4404, reason=f"job not found: {job_id}")
                return
            signature = _signature(payload)
            if signature != last_signature:
                await websocket.send_json(_public(run_id, run_dir, payload).model_dump())
                last_signature = signature
            if payload.get("status") in _TERMINAL:
                break
            await asyncio.sleep(_POLL_SECONDS)
    except WebSocketDisconnect:
        return
    await websocket.close(code=1000)
