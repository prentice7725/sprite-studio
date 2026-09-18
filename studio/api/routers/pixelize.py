# SPDX-License-Identifier: Apache-2.0
"""Pixelize M1.1 API: subject-first deterministic pixel master conversion."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from studio.backend import pixelize_service, static_service


router = APIRouter(prefix="/static", tags=["pixelize"])


class PixelizeRequest(BaseModel):
    strategy: Literal["preserve", "reference_pixel_master_128"] = "preserve"
    asset: str = "scene"
    size: Literal[64, 96, 128, 192] = 128
    palette: Literal["auto", 16, 24, 32, 48] = 32
    detail: Literal["clean", "balanced", "detailed"] = "balanced"
    subject_mode: Literal["auto", "manual"] = "auto"
    subject_bbox: tuple[int, int, int, int] | None = None
    dither: Literal["none", "ordered-low", "ordered"] = "none"
    background: Literal["keep", "cleanup"] = "keep"
    outline: Literal["preserve", "auto"] = "preserve"
    alpha_threshold: int = Field(default=128, ge=1, le=254)


class PixelizeResponse(BaseModel):
    strategy: Literal["preserve", "reference_pixel_master_128"] = "preserve"
    output_asset: str
    preview_asset: str
    subject_asset: str
    palette_asset: str
    profile_asset: str
    report_asset: str
    subject_bbox: tuple[int, int, int, int]
    subject_candidates: list[dict[str, Any]]
    logical_size: tuple[int, int]
    palette_size: int
    palette: list[list[int]]
    warnings: list[dict[str, Any]]
    report: dict[str, Any]
    raw_asset: str | None = None
    intermediate_asset: str | None = None
    post_asset: str | None = None


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
        if body.strategy == "reference_pixel_master_128":
            if body.size != 128:
                raise ValueError("reference_pixel_master_128 requires size=128")
            result_payload = pixelize_service.c2_result_payload(pixelize_service.c2_pixelize_asset(
                info,
                body.asset,
                target_size=128,
                palette_size=None if body.palette == "auto" else int(body.palette),
                alpha_threshold=body.alpha_threshold,
            ))
        else:
            result_payload = pixelize_service.result_payload(pixelize_service.pixelize_asset(
                info,
                body.asset,
                target_size=body.size,
                palette_size=None if body.palette == "auto" else int(body.palette),
                dither=body.dither,
                background=body.background,
                outline=body.outline,
                subject_mode=body.subject_mode,
                subject_bbox=body.subject_bbox,
                detail=body.detail,
                alpha_threshold=body.alpha_threshold,
            ))
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    payload = result_payload
    paths = payload["paths"]
    return PixelizeResponse(
        strategy=body.strategy,
        output_asset=_asset_url(project_id, info.path, paths["output"]),
        preview_asset=_asset_url(project_id, info.path, paths["preview"]),
        subject_asset=_asset_url(project_id, info.path, paths["subject"]),
        palette_asset=_asset_url(project_id, info.path, paths["palette"]),
        profile_asset=_asset_url(project_id, info.path, paths["profile"]),
        report_asset=_asset_url(project_id, info.path, paths["report"]),
        subject_bbox=tuple(payload["subject_bbox"]),
        subject_candidates=payload["subject_candidates"],
        logical_size=tuple(payload["logical_size"]),
        palette_size=int(payload["palette_size"]),
        palette=payload["palette"],
        warnings=payload["warnings"],
        report=payload["report"],
        raw_asset=_asset_url(project_id, info.path, paths["raw"]) if "raw" in paths else None,
        intermediate_asset=_asset_url(project_id, info.path, paths["intermediate"]) if "intermediate" in paths else None,
        post_asset=_asset_url(project_id, info.path, paths["post"]) if "post" in paths else None,
    )