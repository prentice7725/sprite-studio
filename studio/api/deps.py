# SPDX-License-Identifier: Apache-2.0
"""Shared request-scoped helpers every router under `/api/runs/{run_id}/...`
needs: load the run (404/400 on failure), load its request.json, validate a
`state` path segment against it, and turn a local file path a backend
function returned into the asset URL a client fetches (ENDPOINTS.md §Assets)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import HTTPException

from studio.backend import run_manager, spritegen_bridge


def load_run_dir(run_id: str) -> Path:
    try:
        return run_manager.load_run(run_id).path
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def load_run_and_request(run_id: str) -> tuple[Path, dict[str, Any]]:
    run_dir = load_run_dir(run_id)
    request = spritegen_bridge.request_for(run_dir)
    return run_dir, request


def require_state(request: dict[str, Any], state: str) -> None:
    if state not in (request.get("states") or {}):
        raise HTTPException(status_code=404, detail=f"unknown state: {state!r}")


def asset_url(run_id: str, run_dir: Path, path: Path | str) -> str:
    """A backend report's local filesystem path -> the URL that serves it.

    Raises (500, via the unhandled ValueError -> FastAPI's default handler)
    if a path is somehow outside the run directory — that would mean a
    backend function returned a reference this API has no route for, which
    is a bug to surface loudly, not paper over with a path.resolve() that
    quietly changes what was returned.
    """
    rel = Path(path).resolve().relative_to(run_dir.resolve())
    return f"/api/runs/{run_id}/assets/{rel.as_posix()}"
