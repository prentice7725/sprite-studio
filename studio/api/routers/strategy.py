# SPDX-License-Identifier: Apache-2.0
"""Generation strategy and Motion Plan API."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException

from studio.api.contracts import (
    GenerationStrategyResponse,
    KeyPoseApproveRequest,
    SequentialAssetResponse,
    SequentialGenerationResponse,
    StrategyUpdateRequest,
)
from studio.api.deps import asset_url, load_run_and_request, require_state
from studio.backend import sequential_service, strategy_service
from studio.backend.spritegen_bridge import request_for
from sprite_studio.gen.base import GenTimeoutError

router = APIRouter(prefix="/runs/{run_id}/states/{state}", tags=["strategy"])


def _response(run_id: str, run_dir, request: dict, state: str, requested: str | None = None) -> GenerationStrategyResponse:
    plan = strategy_service.motion_plan(run_dir, request, state, requested)
    path = strategy_service.save_motion_plan(run_dir, plan)
    return GenerationStrategyResponse(
        state=state,
        requested=plan["requested"],
        resolved=plan["strategy"],
        reason=plan["reason"],
        policy=strategy_service.policy(),
        motion_plan=plan,
        motion_plan_asset=asset_url(run_id, run_dir, path),
    )


def _run(action):
    try:
        return action()
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except GenTimeoutError as exc:
        raise HTTPException(status_code=504, detail=f"image provider timeout: {exc}") from exc
    except SystemExit as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - preserve strategy failure context
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}") from exc


@router.get("/strategy", response_model=GenerationStrategyResponse)
def get_strategy(run_id: str, state: str) -> GenerationStrategyResponse:
    run_dir, request = load_run_and_request(run_id)
    require_state(request, state)
    return _run(lambda: _response(run_id, run_dir, request, state))


@router.put("/strategy", response_model=GenerationStrategyResponse)
def update_strategy(run_id: str, state: str, body: StrategyUpdateRequest) -> GenerationStrategyResponse:
    run_dir, request = load_run_and_request(run_id)
    require_state(request, state)
    return _run(lambda: (strategy_service.set_override(run_dir, state, body.strategy), _response(run_id, run_dir, request, state, body.strategy))[1])


@router.post("/motion-plan", response_model=GenerationStrategyResponse)
def create_motion_plan(run_id: str, state: str, body: StrategyUpdateRequest | None = None) -> GenerationStrategyResponse:
    run_dir, request = load_run_and_request(run_id)
    require_state(request, state)
    requested = body.strategy if body else None
    return _run(lambda: _response(run_id, run_dir, request, state, requested))


def _sequential_response(run_id: str, run_dir, state: str, manifest: dict) -> SequentialGenerationResponse:
    plan = manifest.get("motion_plan") or strategy_service.motion_plan(run_dir, request_for(run_dir), state, "KEYPOSE_SEQUENTIAL")

    def assets(items: list[dict]) -> list[SequentialAssetResponse]:
        result = []
        for item in items:
            path = Path(str(item.get("path", ""))) if item.get("path") else None
            exists = bool(path and path.is_file())
            result.append(SequentialAssetResponse(
                index=int(item["index"]),
                phase=str(item.get("phase", "unknown")),
                role=str(item.get("role", "key")),
                asset=asset_url(run_id, run_dir, path) if exists and path else None,
                status="generated" if exists else "missing",
            ))
        return result

    return SequentialGenerationResponse(
        state=state,
        status=str(manifest.get("status", "planned")),
        motion_plan=plan,
        key_poses=assets(list(manifest.get("key_poses") or [])),
        inbetweens=assets(list(manifest.get("inbetweens") or [])),
    )


def _sequential_context(run_id: str, state: str):
    run_dir, request = load_run_and_request(run_id)
    require_state(request, state)
    return run_dir, request


@router.get("/sequential", response_model=SequentialGenerationResponse)
def get_sequential(run_id: str, state: str) -> SequentialGenerationResponse:
    run_dir, _request = _sequential_context(run_id, state)
    return _run(lambda: _sequential_response(run_id, run_dir, state, sequential_service.load_manifest(run_dir, state)))


@router.post("/sequential/key-poses", response_model=SequentialGenerationResponse)
def generate_key_poses(run_id: str, state: str) -> SequentialGenerationResponse:
    run_dir, _request = _sequential_context(run_id, state)
    return _run(lambda: _sequential_response(run_id, run_dir, state, sequential_service.generate_key_poses(run_dir, state)))


@router.post("/sequential/approve", response_model=SequentialGenerationResponse)
def approve_key_poses(run_id: str, state: str, body: KeyPoseApproveRequest) -> SequentialGenerationResponse:
    run_dir, _request = _sequential_context(run_id, state)
    return _run(lambda: _sequential_response(run_id, run_dir, state, sequential_service.approve_key_poses(run_dir, state, body.indices)))


@router.post("/sequential/inbetweens", response_model=SequentialGenerationResponse)
def generate_inbetweens(run_id: str, state: str) -> SequentialGenerationResponse:
    run_dir, _request = _sequential_context(run_id, state)
    return _run(lambda: _sequential_response(run_id, run_dir, state, sequential_service.generate_inbetweens(run_dir, state)))
