# SPDX-License-Identifier: Apache-2.0
"""/api/runs — ENDPOINTS.md §"Sprite Mode — Project / Runs"."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response

from studio.api.contracts import CreateRunRequest, RunDetail, RunStatusResponse, RunSummary
from studio.api.uploads import resolve_upload
from studio.backend import run_manager
from studio.backend.schemas import RunInfo, StudioRunConfig

router = APIRouter(prefix="/runs", tags=["runs"])


def _summary(info: RunInfo) -> RunSummary:
    return RunSummary(
        run_id=info.run_id,
        character_id=info.character_id,
        provider=info.provider,
        preset=info.preset,
        mode=info.mode,
        directions=list(info.directions),
        states=list(info.states),
    )


def _detail(info: RunInfo) -> RunDetail:
    return RunDetail(
        **_summary(info).model_dump(),
        cell_size=info.cell_size,
        runtime_size=info.runtime_size,
        generation_profile=info.generation_profile,
        background_policy=info.background_policy,
        refine=dict(info.refine),
        locks=dict(info.locks),
    )


def _load_or_404(run_id: str) -> RunInfo:
    try:
        return run_manager.load_run(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("", response_model=RunDetail, status_code=201)
def create_run(body: CreateRunRequest) -> RunDetail:
    base_image = resolve_upload(body.base_image_upload_id) if body.base_image_upload_id else None
    # `locks=None` must not be passed through — StudioRunConfig's own
    # default_factory supplies the real default; passing the literal None
    # would overwrite it instead of falling back to it.
    config_kwargs: dict = dict(
        run_id=body.run_id,
        character_id=body.character_id,
        provider=body.provider,
        base_image=base_image,
        directions=tuple(body.directions),
        mirrors=dict(body.mirrors),
        # StudioRunConfig.states is keyed by plain pose name ("idle",
        # "attack"), never direction-prefixed — run_manager._request_input
        # is what crosses it with `directions` into "side_idle" etc.
        states={name: spec.model_dump() for name, spec in body.states.items()},
        cell_size=body.cell_size,
        runtime_size=body.runtime_size,
        preset=body.preset,
        description=body.description,
        generation_profile=body.generation_profile,
        background_policy=body.background_policy,
    )
    if body.locks is not None:
        config_kwargs["locks"] = body.locks
    try:
        config = StudioRunConfig(**config_kwargs)
        info = run_manager.create_run(config)
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SystemExit as exc:
        # `prepare.run()`'s own CLI-style validation (layer/rig config,
        # malformed directions) fails loud with SystemExit — a BaseException
        # FastAPI's default handling does not catch (see generate.py's
        # module docstring for why every route here does this explicitly).
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _detail(info)


@router.get("", response_model=list[RunSummary])
def list_runs() -> list[RunSummary]:
    return [_summary(info) for info in run_manager.list_runs()]


@router.get("/{run_id}", response_model=RunDetail)
def get_run(run_id: str) -> RunDetail:
    return _detail(_load_or_404(run_id))


@router.get("/{run_id}/status", response_model=RunStatusResponse)
def get_run_status(run_id: str) -> RunStatusResponse:
    _load_or_404(run_id)  # 404s before get_run_status's own KeyError-shaped failures
    return RunStatusResponse(states=run_manager.get_run_status(run_id))


@router.delete("/{run_id}", status_code=204, response_class=Response)
def delete_run(run_id: str) -> Response:
    _load_or_404(run_id)
    run_manager.delete_run(run_id)
    return Response(status_code=204)
