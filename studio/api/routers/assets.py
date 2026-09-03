# SPDX-License-Identifier: Apache-2.0
"""GET /api/runs/{run_id}/assets/{path} — ENDPOINTS.md §Assets.

Every image/file the Gradio UI loaded from a local path becomes a URL here
instead of a JSON-embedded base64 blob. `run_id` is resolved through
`run_manager.load_run` (so the same 404 contract as every other run route
applies); `path` is resolved under that run's own directory and must never be
allowed to escape it via `..` or an absolute-path component.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from studio.backend import run_manager

router = APIRouter(prefix="/runs", tags=["assets"])


def _resolve_contained(root: Path, relative: str) -> Path:
    """`root / relative`, refusing to resolve to anything outside `root`.

    `Path.is_relative_to` (3.9+) is checked against the fully resolved
    (symlink-followed) form on both sides — a relative path containing `..`
    or an OS-absolute component (Windows drive letter, POSIX leading `/`)
    must not be able to walk out of the run directory just because a client
    controls the `{path:path}` segment.
    """
    root = root.resolve()
    candidate = (root / relative).resolve()
    if not candidate.is_relative_to(root):
        raise HTTPException(status_code=400, detail="asset path escapes the run directory")
    return candidate


@router.get("/{run_id}/assets/{asset_path:path}")
def get_run_asset(run_id: str, asset_path: str) -> FileResponse:
    try:
        info = run_manager.load_run(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    resolved = _resolve_contained(info.path, asset_path)
    if not resolved.is_file():
        raise HTTPException(status_code=404, detail=f"asset not found: {asset_path}")
    return FileResponse(resolved)
