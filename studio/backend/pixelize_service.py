# SPDX-License-Identifier: Apache-2.0
"""Persist Pixelize M1.1 outputs inside a Static project."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from studio.backend.schemas import StaticProjectInfo
from studio.static_mode.pixelize import PixelizeOptions, PixelizeResult, pixelize_file
from studio.static_mode.pixelize.c2 import C2Options, C2Result, c2_pixel_master_file

_SAFE_ASSET = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


def pixelize_asset(
    info: StaticProjectInfo,
    asset: str = "scene",
    *,
    target_size: int = 128,
    palette_size: int | None = 32,
    dither: str = "none",
    background: str = "keep",
    outline: str = "preserve",
    subject_mode: str = "auto",
    subject_bbox: tuple[int, int, int, int] | None = None,
    detail: str = "balanced",
    alpha_threshold: int = 128,
) -> PixelizeResult:
    if not _SAFE_ASSET.fullmatch(asset):
        raise ValueError(f"invalid asset name: {asset!r}")
    source = info.path / "raw" / f"{asset}.png"
    if not source.is_file():
        raise FileNotFoundError(f"no raw asset to pixelize: {source}")
    options = PixelizeOptions(
        target_size=target_size,
        palette_size=palette_size,
        dither=dither,  # type: ignore[arg-type]
        background=background,  # type: ignore[arg-type]
        outline=outline,  # type: ignore[arg-type]
        subject_mode=subject_mode,  # type: ignore[arg-type]
        subject_bbox=subject_bbox,
        detail=detail,  # type: ignore[arg-type]
        alpha_threshold=alpha_threshold,
    )
    return pixelize_file(source, info.path / "pixelized", options, stem=asset)


def c2_pixelize_asset(
    info: StaticProjectInfo,
    asset: str = "scene",
    *,
    target_size: int = 128,
    palette_size: int | None = None,
    alpha_threshold: int = 128,
    accepted: str = "post",
) -> C2Result:
    if not _SAFE_ASSET.fullmatch(asset):
        raise ValueError(f"invalid asset name: {asset!r}")
    source = info.path / "raw" / f"{asset}.png"
    if not source.is_file():
        raise FileNotFoundError(f"no raw asset to pixelize: {source}")
    return c2_pixel_master_file(
        source,
        info.path / "pixelized" / asset,
        provider=info.provider,
        options=C2Options(target_size=target_size, palette_size=palette_size, alpha_threshold=alpha_threshold, accepted=accepted),
        stem=asset,
        workdir=info.path / "static" / "work" / asset / "c2",
    )

def c2_result_payload(result: C2Result) -> dict[str, Any]:
    if result.accepted_path is None or result.post_path is None or result.preview_path is None or result.palette_path is None or result.profile_path is None:
        status = str(result.report.get("status") or "FAIL_LOGICAL_GRID")
        raise ValueError(status)
    return {
        "logical_size": list(result.logical_size),
        "subject_asset": result.post_path,
        "subject_bbox": list(result.subject_bbox),
        "subject_candidates": [],
        "palette_size": len(result.palette),
        "palette": [list(entry) for entry in result.palette[:128]],
        "warnings": list(result.warnings),
        "report": result.report,
        "paths": {
            "output": result.accepted_path,
            "palette": result.palette_path,
            "profile": result.profile_path,
            "report": result.report_path,
            "preview": result.preview_path,
            "subject": result.post_path,
            "raw": result.raw_path,
            "intermediate": result.intermediate_path,
            "post": result.post_path,
        },
        "strategy": "reference_pixel_master_128",
    }


def result_payload(result: PixelizeResult) -> dict[str, Any]:
    return {
        "logical_size": list(result.logical_size),
        "subject_asset": result.subject_path,
        "subject_bbox": list(result.subject_bbox),
        "subject_candidates": list(result.subject_candidates),
        "palette_size": len(result.palette),
        "palette": [list(entry) for entry in result.palette],
        "warnings": list(result.warnings),
        "report": result.report,
        "paths": {
            "output": result.output_path,
            "palette": result.palette_path,
            "profile": result.profile_path,
            "report": result.report_path,
            "preview": result.preview_path,
            "subject": result.subject_path,
        },
    }
