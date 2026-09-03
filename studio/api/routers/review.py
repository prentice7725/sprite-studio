# SPDX-License-Identifier: Apache-2.0
"""Sprite review, repair, animation QA, curation, and export routes.

These routes are intentionally thin adapters.  The existing Studio services
remain the source of truth; this module only validates the run/state, converts
local files into asset URLs, and maps service failures to HTTP responses.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, HTTPException

from studio.api.contracts import (
    AiMicroFixApplyRequest,
    AiMicroFixApplyResponse,
    AiMicroFixPrepareRequest,
    AiMicroFixPrepareResponse,
    AnchorClearRequest,
    AnchorPinRequest,
    AnchorStatusResponse,
    AnimationQaResponse,
    ComposeResponse,
    CurationLaunchResponse,
    RepairDecideRequest,
    ReviewDataResponse,
    RuntimeExportResponse,
)
from studio.api.deps import asset_url, load_run_dir, load_run_and_request, require_state
from studio.api.uploads import resolve_upload
from studio.backend import (
    anchor_service,
    animation_qa,
    export_service,
    history_service,
    qa_service,
    repair_service,
    spritegen_bridge,
)
from sprite_studio.spec.layout import frames_dir_rel, row_frame_rel

router = APIRouter(tags=["review", "repair", "qa", "export"])


def _action(action: Callable[[], Any]) -> Any:
    try:
        return action()
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SystemExit as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - preserve service failure context
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}") from exc


def _manifest_frames(run_dir: Path, state: str) -> list[Path]:
    manifest_path = run_dir / "frames" / "frames-manifest.json"
    if not manifest_path.is_file():
        return []
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    row = next((item for item in manifest.get("rows", []) if item.get("state") == state), None)
    if not row:
        return []
    return [run_dir / row_frame_rel(row, index) for index in range(len(row.get("files", [])))]


def _review_response(run_id: str, run_dir: Path, request: dict[str, Any], state: str) -> ReviewDataResponse:
    data = repair_service.review_data(run_dir, state)
    refined_dir = run_dir / frames_dir_rel(request, state) / "refined"
    refined = sorted(refined_dir.glob("frame-*.png")) if refined_dir.is_dir() else []
    candidates = data.get("candidates") or []
    return ReviewDataResponse(
        frames=[asset_url(run_id, run_dir, path) for path in _manifest_frames(run_dir, state) if path.is_file()],
        refined_frames=[asset_url(run_id, run_dir, path) for path in refined if path.is_file()],
        repair_proposals=[asset_url(run_id, run_dir, path) for path in data.get("proposal_files", []) if Path(path).is_file()],
        repaired_frames=[asset_url(run_id, run_dir, path) for path in data.get("repaired_files", []) if Path(path).is_file()],
        repair_diff=[asset_url(run_id, run_dir, path) for path in data.get("diff_files", []) if Path(path).is_file()],
        repair_candidates=[str(item["id"]) for item in candidates],
        repair_summary=repair_service.summary(run_dir, state),
        qa_summary=qa_service.summary(run_dir, state),
        history_summary=history_service.summary(run_dir, state),
    )


def _validated_state(run_id: str, state: str) -> tuple[Path, dict[str, Any]]:
    run_dir, request = load_run_and_request(run_id)
    require_state(request, state)
    return run_dir, request


@router.get("/runs/{run_id}/states/{state}/review", response_model=ReviewDataResponse)
def review(run_id: str, state: str) -> ReviewDataResponse:
    run_dir, request = _validated_state(run_id, state)
    return _action(lambda: _review_response(run_id, run_dir, request, state))


@router.post("/runs/{run_id}/states/{state}/repair/analyze", response_model=ReviewDataResponse)
def repair_analyze(run_id: str, state: str) -> ReviewDataResponse:
    run_dir, request = _validated_state(run_id, state)
    return _action(lambda: (repair_service.analyze_state(run_dir, state), _review_response(run_id, run_dir, request, state))[1])


@router.post("/runs/{run_id}/states/{state}/repair/safe", response_model=ReviewDataResponse)
def repair_safe(run_id: str, state: str) -> ReviewDataResponse:
    run_dir, request = _validated_state(run_id, state)

    def execute() -> ReviewDataResponse:
        repair_service.analyze_state(run_dir, state)
        repair_service.repair_state(run_dir, state)
        return _review_response(run_id, run_dir, request, state)

    return _action(execute)


@router.post("/runs/{run_id}/states/{state}/repair/decide", response_model=ReviewDataResponse)
def repair_decide(run_id: str, state: str, body: RepairDecideRequest) -> ReviewDataResponse:
    run_dir, request = _validated_state(run_id, state)
    return _action(lambda: (
        repair_service.decide_candidates(run_dir, state, set(body.candidate_ids), accept=body.accept),
        _review_response(run_id, run_dir, request, state),
    )[1])


@router.post("/runs/{run_id}/states/{state}/repair/undo", response_model=ReviewDataResponse)
def repair_undo(run_id: str, state: str) -> ReviewDataResponse:
    run_dir, request = _validated_state(run_id, state)
    return _action(lambda: (repair_service.clear_repairs(run_dir, state), _review_response(run_id, run_dir, request, state))[1])


@router.post("/runs/{run_id}/states/{state}/repair/adopt", response_model=ReviewDataResponse)
def repair_adopt(run_id: str, state: str) -> ReviewDataResponse:
    run_dir, request = _validated_state(run_id, state)
    return _action(lambda: (repair_service.adopt_repaired(run_dir, state), _review_response(run_id, run_dir, request, state))[1])


@router.post("/runs/{run_id}/states/{state}/repair/unadopt", response_model=ReviewDataResponse)
def repair_unadopt(run_id: str, state: str) -> ReviewDataResponse:
    run_dir, request = _validated_state(run_id, state)
    return _action(lambda: (repair_service.unadopt_repaired(run_dir, state), _review_response(run_id, run_dir, request, state))[1])


@router.post("/runs/{run_id}/states/{state}/repair/ai-micro-fix/prepare", response_model=AiMicroFixPrepareResponse)
def repair_ai_prepare(run_id: str, state: str, body: AiMicroFixPrepareRequest) -> AiMicroFixPrepareResponse:
    run_dir, _request = _validated_state(run_id, state)

    def execute() -> AiMicroFixPrepareResponse:
        job = repair_service.prepare_ai_micro_fix(run_dir, state, set(body.candidate_ids))
        return AiMicroFixPrepareResponse(
            job_id=job["job_id"],
            before_asset=asset_url(run_id, run_dir, job["before_path"]),
            mask_asset=asset_url(run_id, run_dir, job["mask_path"]),
            job_dir=job["job_dir"],
        )

    return _action(execute)


@router.post("/runs/{run_id}/states/{state}/repair/ai-micro-fix/apply", response_model=AiMicroFixApplyResponse)
def repair_ai_apply(run_id: str, state: str, body: AiMicroFixApplyRequest) -> AiMicroFixApplyResponse:
    run_dir, request = _validated_state(run_id, state)
    result_path = resolve_upload(body.result_upload_id)

    def execute() -> AiMicroFixApplyResponse:
        result = repair_service.apply_ai_micro_fix(run_dir, state, body.job_id, result_path)
        review_result = _review_response(run_id, run_dir, request, state)
        return AiMicroFixApplyResponse(review=review_result, pixels_changed=int(result["ai_micro_fix"]["pixels_changed"]))

    return _action(execute)


@router.get("/runs/{run_id}/anchors", response_model=AnchorStatusResponse)
def anchors(run_id: str) -> AnchorStatusResponse:
    run_dir = load_run_dir(run_id)
    return _action(lambda: AnchorStatusResponse(summary=anchor_service.summary(run_dir), directions=anchor_service.status(run_dir)))


@router.post("/runs/{run_id}/anchors/pin", response_model=AnchorStatusResponse)
def anchor_pin(run_id: str, body: AnchorPinRequest) -> AnchorStatusResponse:
    run_dir, _request = _validated_state(run_id, body.state)
    return _action(lambda: (anchor_service.pin(run_dir, body.state, body.index), AnchorStatusResponse(summary=anchor_service.summary(run_dir), directions=anchor_service.status(run_dir)))[1])


@router.post("/runs/{run_id}/anchors/clear", response_model=AnchorStatusResponse)
def anchor_clear(run_id: str, body: AnchorClearRequest) -> AnchorStatusResponse:
    run_dir = load_run_dir(run_id)
    return _action(lambda: (anchor_service.clear(run_dir, body.direction), AnchorStatusResponse(summary=anchor_service.summary(run_dir), directions=anchor_service.status(run_dir)))[1])


@router.post("/runs/{run_id}/states/{state}/animation-qa", response_model=AnimationQaResponse)
def animation_quality(run_id: str, state: str) -> AnimationQaResponse:
    run_dir, _request = _validated_state(run_id, state)

    def execute() -> AnimationQaResponse:
        result = spritegen_bridge.animation_qa(run_dir, state)
        warnings = [f"{item.get('code', 'WARNING')}: {item.get('message', '')}" for item in result.warnings]
        summary = "Animation QA PASS — no continuity warnings." if result.ok and not warnings else "\n".join(warnings) or "Animation QA failed."
        return AnimationQaResponse(ok=result.ok and not warnings, warnings=warnings, summary=summary)

    return _action(execute)


@router.post("/runs/{run_id}/curation", response_model=CurationLaunchResponse)
def curation(run_id: str) -> CurationLaunchResponse:
    run_dir = load_run_dir(run_id)
    return _action(lambda: CurationLaunchResponse(url=spritegen_bridge.launch_curation(run_dir)))


@router.post("/runs/{run_id}/export/compose", response_model=ComposeResponse)
def export_compose(run_id: str) -> ComposeResponse:
    run_dir = load_run_dir(run_id)

    def execute() -> ComposeResponse:
        code = export_service.compose(run_dir)
        if code != 0:
            raise RuntimeError(f"compose failed with exit code {code}")
        return ComposeResponse(
            sprite_sheet_asset=asset_url(run_id, run_dir, run_dir / "sprite-sheet-alpha.png"),
            manifest_asset=asset_url(run_id, run_dir, run_dir / "manifest.json"),
        )

    return _action(execute)


@router.post("/runs/{run_id}/export/runtime", response_model=RuntimeExportResponse)
def export_runtime(run_id: str) -> RuntimeExportResponse:
    run_dir = load_run_dir(run_id)

    def execute() -> RuntimeExportResponse:
        result = export_service.build_runtime(run_dir)
        return RuntimeExportResponse(
            atlas_asset=asset_url(run_id, run_dir, result["atlas"]),
            manifest_asset=asset_url(run_id, run_dir, result["manifest"]),
            size=tuple(result["size"]),
        )

    return _action(execute)
