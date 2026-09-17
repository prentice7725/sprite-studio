# SPDX-License-Identifier: Apache-2.0
"""Pixelize M1 API: turn one Static raw illustration into a pixel master."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from studio.backend import pixelize_service, static_service


router = APIRouter(prefix="/static", tags=["pixelize"])


class PixelizeRequest(BaseModel):
    asset: str = "scene"
    size: Literal[64, 96, 128, 192] = 128
    palette: Literal["auto", 16, 24, 32, 48] = 32
    dither: Literal["none", "ordered-low", "ordered"] = "none"
    background: Literal["keep", "cleanup"] = "keep"
    outline: Literal["preserve", "auto"] = "preserve"


class PixelizeResponse(BaseModel):
    output_asset: str
    preview_asset: str
    palette_asset: str
    profile_asset: str
    report_asset: str
    logical_size: tuple[int, int]
    palette_size: int
    palette: list[list[int]]
    warnings: list[dict[str, Any]]
    report: dict[str, Any]


def _load(project_id: str):
    try:
        return static_service.load_project(project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _asset_url(project_id: str, project_root: Path, path: Path) -> str:
    root = project_root.resolve()
    candidate = path.resolve()
    try:
        relative = candidate.relative_to(root).as_posix()
    except ValueError as exc:
        raise HTTPException(status_code=500, detail="pixelize service returned an asset outside the project") from exc
    return f"/api/static/{project_id}/assets/{relative}"


@router.post("/{project_id}/pixelize", response_model=PixelizeResponse)
def pixelize_static_asset(project_id: str, body: PixelizeRequest) -> PixelizeResponse:
    info = _load(project_id)
    try:
        result = pixelize_service.pixelize_asset(
            info,
            body.asset,
            target_size=body.size,
            palette_size=None if body.palette == "auto" else int(body.palette),
            dither=body.dither,
            background=body.background,
            outline=body.outline,
        )
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    payload = pixelize_service.result_payload(result)
    paths = payload["paths"]
    return PixelizeResponse(
        output_asset=_asset_url(project_id, info.path, paths["output"]),
        preview_asset=_asset_url(project_id, info.path, paths["preview"]),
        palette_asset=_asset_url(project_id, info.path, paths["palette"]),
        profile_asset=_asset_url(project_id, info.path, paths["profile"]),
        report_asset=_asset_url(project_id, info.path, paths["report"]),
        logical_size=tuple(payload["logical_size"]),
        palette_size=int(payload["palette_size"]),
        palette=payload["palette"],
        warnings=payload["warnings"],
        report=payload["report"],
    )
