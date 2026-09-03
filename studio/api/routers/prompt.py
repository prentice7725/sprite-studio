# SPDX-License-Identifier: Apache-2.0
"""GET/PUT/DELETE .../prompt[/blocks|/override] — ENDPOINTS.md §"Sprite Mode —
Prompt". Thin wrappers over `studio.backend.prompt_service` — see that
module's own docstring (and SPRITE_STUDIO_PROMPT_PIPELINE_REGRESSION_FIX_
DIRECTIVE) for why the merged prompt looks the way it does; this router does
not re-decide any of that, only serializes it."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from studio.api.contracts import PromptBlocksResponse, PromptResponse, SavePromptOverrideRequest
from studio.api.deps import load_run_and_request, require_state
from studio.backend import prompt_service

router = APIRouter(prefix="/runs/{run_id}/states/{state}", tags=["prompt"])


@router.get("/prompt", response_model=PromptResponse)
def get_prompt(run_id: str, state: str) -> PromptResponse:
    run_dir, request = load_run_and_request(run_id)
    require_state(request, state)
    text, source = prompt_service.effective_prompt(run_dir, request, state)
    return PromptResponse(state=state, prompt=text, source=source)


@router.get("/prompt/blocks", response_model=PromptBlocksResponse)
def get_prompt_blocks(run_id: str, state: str) -> PromptBlocksResponse:
    run_dir, request = load_run_and_request(run_id)
    require_state(request, state)
    result = prompt_service.assemble_for_run(run_dir, request, state)
    return PromptBlocksResponse(
        state=state, target_kind=result.target_kind, frame_count=result.frame_count, blocks=result.blocks,
    )


@router.put("/prompt/override", response_model=PromptResponse)
def save_prompt_override(run_id: str, state: str, body: SavePromptOverrideRequest) -> PromptResponse:
    run_dir, request = load_run_and_request(run_id)
    require_state(request, state)
    try:
        prompt_service.save_override(run_dir, state, body.prompt)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    text, source = prompt_service.effective_prompt(run_dir, request, state)
    return PromptResponse(state=state, prompt=text, source=source)


@router.delete("/prompt/override", response_model=PromptResponse)
def reset_prompt_override(run_id: str, state: str) -> PromptResponse:
    run_dir, request = load_run_and_request(run_id)
    require_state(request, state)
    prompt_service.reset_override(run_dir, state)
    text, source = prompt_service.effective_prompt(run_dir, request, state)
    return PromptResponse(state=state, prompt=text, source=source)
