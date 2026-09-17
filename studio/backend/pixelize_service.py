# SPDX-License-Identifier: Apache-2.0
"""Persist Pixelize M1 outputs inside a Static project."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from studio.backend.schemas import StaticProjectInfo
from studio.static_mode.pixelize import PixelizeOptions, PixelizeResult, pixelize_file

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
    )
    return pixelize_file(source, info.path / "pixelized", options, stem=asset)


def result_payload(result: PixelizeResult) -> dict[str, Any]:
    return {
        "logical_size": list(result.logical_size),
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
        },
    }
