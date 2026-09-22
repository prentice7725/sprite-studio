# SPDX-License-Identifier: Apache-2.0
"""Source-first Quick Generate API.

This router intentionally exposes user concepts (source, pixelize, sprite)
while keeping Run/State/Preset/Job details behind the existing Studio APIs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from sprite_studio.gen.base import GenTimeoutError
from studio.api.contracts import (
    QuickMakeSpriteRequest,
    QuickMakeSpriteResponse,
    QuickPixelizeRequest,
    QuickPixelizeResponse,
    QuickSessionCreateRequest,
    QuickSessionResponse,
    QuickSourceSelectionRequest,
)
from studio.backend import quick_auto_service, quick_c2_service, quick_service


router = APIRouter(prefix="/quick", tags=["quick-generate"])


def _action(action: Callable[[], Any]) -> Any:
    try:
        return action()
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except GenTimeoutError as exc:
        raise HTTPException(status_code=504, detail=f"image provider timeout: {exc}") from exc
    except SystemExit as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - preserve service failure context
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}") from exc


def _session(payload: dict[str, Any]) -> QuickSessionResponse:
    return QuickSessionResponse.model_validate(quick_service._response_payload(payload))


def _load(session_id: str) -> dict[str, Any]:
    return _action(lambda: quick_service.load_session(session_id))


@router.post("/sessions", response_model=QuickSessionResponse, status_code=201)
def create_session(body: QuickSessionCreateRequest) -> QuickSessionResponse:
    return _session(_action(lambda: quick_service.create_session(body)))


@router.get("/sessions/{session_id}", response_model=QuickSessionResponse)
def get_session(session_id: str) -> QuickSessionResponse:
    return _session(_load(session_id))


@router.post("/sessions/{session_id}/pixelize", response_model=QuickPixelizeResponse)
def pixelize(session_id: str, body: QuickPixelizeRequest) -> QuickPixelizeResponse:
    payload, detail = _action(
        lambda: quick_c2_service.pixelize_c2_session(session_id, body)
        if body.strategy == "reference_pixel_master_128"
        else quick_auto_service.pixelize_auto_session(session_id, body)
        if body.strategy == "identity_preserving_auto"
        else quick_service.pixelize_session(session_id, body)
    )
    del payload
    return QuickPixelizeResponse.model_validate(detail)


@router.put("/sessions/{session_id}/source", response_model=QuickSessionResponse)
def select_source(session_id: str, body: QuickSourceSelectionRequest) -> QuickSessionResponse:
    return _session(_action(lambda: quick_service.select_source(session_id, body.source)))


@router.post("/sessions/{session_id}/make-sprite", response_model=QuickMakeSpriteResponse, status_code=202)
def make_sprite(session_id: str, body: QuickMakeSpriteRequest) -> QuickMakeSpriteResponse:
    payload, run_id, target_state, job_id = _action(lambda: quick_service.make_sprite(session_id, body))
    return QuickMakeSpriteResponse(
        session=_session(payload),
        run_id=run_id,
        target_state=target_state,
        job_id=job_id,
    )


@router.get("/sessions/{session_id}/assets/{asset_path:path}")
def get_asset(session_id: str, asset_path: str) -> FileResponse:
    payload = _load(session_id)
    root = quick_service._session_dir(str(payload["session_id"])).resolve()
    candidate = (root / asset_path).resolve()
    if not candidate.is_relative_to(root):
        raise HTTPException(status_code=400, detail="quick asset path escapes the session")
    if not candidate.is_file():
        raise HTTPException(status_code=404, detail=f"asset not found: {asset_path}")
    return FileResponse(candidate)
