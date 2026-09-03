# SPDX-License-Identifier: Apache-2.0
"""FastAPI adapters for the existing Static Mode service."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from studio.api.contracts import (
    CreateStaticProjectRequest,
    StaticCleanupRequest,
    StaticCleanupResponse,
    StaticExportResponse,
    StaticGenerateRequest,
    StaticGenerateResponse,
    StaticImportRequest,
    StaticLayersRequest,
    StaticLayersResponse,
    StaticPromptResponse,
    StaticProjectStatusResponse,
    StaticProjectSummary,
    StaticQaResponse,
    StaticRefineRequest,
    StaticRefineResponse,
    StaticSeamRequest,
    StaticSeamResponse,
)
from studio.api.uploads import resolve_upload
from studio.backend import preset_service, static_service
from studio.backend.schemas import StaticProjectConfig
from studio.static_mode.prompt import StaticPromptAssembler

router = APIRouter(prefix="/static", tags=["static"])


def _action(action: Callable[[], Any]) -> Any:
    try:
        return action()
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SystemExit as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - preserve service failure context
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}") from exc


def _summary(info: Any) -> StaticProjectSummary:
    return StaticProjectSummary(
        project_id=info.project_id,
        provider=info.provider,
        asset_type=info.asset_type,
        style_profile=info.style_profile,
        tileable=info.tileable,
        export_size=info.export_size,
        layer_intent=info.layer_intent,
        background_policy=info.background_policy,
    )


def _load(project_id: str) -> Any:
    try:
        return static_service.load_project(project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _asset_url(project_id: str, path: Path | str) -> str:
    info = _load(project_id)
    root = info.path.resolve()
    candidate = Path(path).resolve()
    try:
        relative = candidate.relative_to(root).as_posix()
    except ValueError as exc:
        raise HTTPException(status_code=500, detail="static service returned an asset outside the project") from exc
    return f"/api/static/{project_id}/assets/{relative}"


@router.get("/presets", response_model=list[str])
def list_static_presets() -> list[str]:
    return _action(preset_service.list_static_presets)


@router.get("/presets/{preset_id}")
def get_static_preset(preset_id: str) -> dict[str, Any]:
    return _action(lambda: preset_service.load_static_preset(preset_id))


@router.post("", response_model=StaticProjectSummary, status_code=201)
def create_static_project(body: CreateStaticProjectRequest) -> StaticProjectSummary:
    base_image = resolve_upload(body.base_image_upload_id) if body.base_image_upload_id else None
    config = StaticProjectConfig(
        project_id=body.project_id,
        provider=body.provider,
        asset_type=body.asset_type,
        style_profile=body.style_profile,
        description=body.description,
        base_image=base_image,
        tileable=body.tileable,
        export_size=body.export_size,
        layer_intent=body.layer_intent,
        background_policy=body.background_policy,
    )
    return _action(lambda: _summary(static_service.create_project(config)))


@router.get("", response_model=list[StaticProjectSummary])
def list_static_projects() -> list[StaticProjectSummary]:
    return _action(lambda: [_summary(info) for info in static_service.list_projects()])


@router.get("/{project_id}", response_model=StaticProjectSummary)
def get_static_project(project_id: str) -> StaticProjectSummary:
    return _summary(_load(project_id))


@router.get("/{project_id}/assets/{asset_path:path}")
def get_static_asset(project_id: str, asset_path: str) -> FileResponse:
    info = _load(project_id)
    root = info.path.resolve()
    candidate = (root / asset_path).resolve()
    if not candidate.is_relative_to(root):
        raise HTTPException(status_code=400, detail="asset path escapes the static project")
    if not candidate.is_file():
        raise HTTPException(status_code=404, detail=f"asset not found: {asset_path}")
    return FileResponse(candidate)


@router.get("/{project_id}/status", response_model=StaticProjectStatusResponse)
def static_status(project_id: str) -> StaticProjectStatusResponse:
    info = _load(project_id)
    return _action(lambda: StaticProjectStatusResponse(assets=static_service.project_status(info)))


@router.get("/{project_id}/prompt", response_model=StaticPromptResponse)
def static_prompt(project_id: str) -> StaticPromptResponse:
    info = _load(project_id)

    def assemble() -> StaticPromptResponse:
        base = info.path / "raw" / "base.png"
        result = StaticPromptAssembler().assemble(
            info.project_id,
            info.description,
            asset_type=info.asset_type,
            style_profile=info.style_profile,
            tileable=info.tileable,
            layer_intent=info.layer_intent,
            background_policy=info.background_policy,
            base_image=base if base.is_file() else None,
            export_size=info.export_size,
        )
        return StaticPromptResponse(prompt=result.final_prompt, issues=[issue.message for issue in result.issues])

    return _action(assemble)


@router.post("/{project_id}/generate", response_model=StaticGenerateResponse)
def static_generate(project_id: str, body: StaticGenerateRequest) -> StaticGenerateResponse:
    info = _load(project_id)

    def generate() -> StaticGenerateResponse:
        report = static_service.generate_asset(info, body.asset, prompt_override=body.prompt_override, provider=body.provider)
        return StaticGenerateResponse(
            asset=body.asset,
            provider=str(report.get("provider", info.provider)),
            elapsed_seconds=float(report.get("elapsed_seconds", 0)),
            out_asset=_asset_url(project_id, info.path / "raw" / f"{body.asset}.png"),
        )

    return _action(generate)


@router.post("/{project_id}/import", response_model=StaticGenerateResponse)
def static_import(project_id: str, body: StaticImportRequest) -> StaticGenerateResponse:
    info = _load(project_id)
    source = resolve_upload(body.upload_id)

    def import_image() -> StaticGenerateResponse:
        output = static_service.import_asset(info, source, asset=body.asset)
        return StaticGenerateResponse(asset=body.asset, provider="import", elapsed_seconds=0, out_asset=_asset_url(project_id, output))

    return _action(import_image)


@router.post("/{project_id}/refine", response_model=StaticRefineResponse)
def static_refine(project_id: str, body: StaticRefineRequest) -> StaticRefineResponse:
    info = _load(project_id)

    def refine() -> StaticRefineResponse:
        report = static_service.refine_asset(info, body.asset, cleanup=body.cleanup)
        return StaticRefineResponse(output_asset=_asset_url(project_id, info.path / "refined" / f"{body.asset}.png"), report=report)

    return _action(refine)


@router.post("/{project_id}/cleanup", response_model=StaticCleanupResponse)
def static_cleanup(project_id: str, body: StaticCleanupRequest) -> StaticCleanupResponse:
    info = _load(project_id)
    return _action(lambda: StaticCleanupResponse(
        output_asset=_asset_url(project_id, info.path / "refined" / f"{body.asset}.png"),
        report=static_service.cleanup_asset(info, body.asset, orphan_max_area=body.orphan_max_area, fill_max_area=body.hole_max_area),
    ))


def _seam(project_id: str, body: StaticSeamRequest) -> StaticSeamResponse:
    info = _load(project_id)
    report = static_service.check_tileability(info, body.asset, repair=body.repair)
    return StaticSeamResponse(wrap_preview_asset=_asset_url(project_id, report["wrap_preview"]), report=report)


@router.post("/{project_id}/seam-check", response_model=StaticSeamResponse)
def seam_check(project_id: str, body: StaticSeamRequest) -> StaticSeamResponse:
    return _action(lambda: _seam(project_id, body.model_copy(update={"repair": False})))


@router.post("/{project_id}/seam-repair", response_model=StaticSeamResponse)
def seam_repair(project_id: str, body: StaticSeamRequest) -> StaticSeamResponse:
    return _action(lambda: _seam(project_id, body.model_copy(update={"repair": True})))


@router.post("/{project_id}/layers/split", response_model=StaticLayersResponse)
def split_layers(project_id: str, body: StaticLayersRequest) -> StaticLayersResponse:
    info = _load(project_id)

    def process() -> StaticLayersResponse:
        report = static_service.process_layers(info, body.asset, cutout=False)
        directory = Path(report["output_dir"])
        assets = [_asset_url(project_id, path) for path in sorted(directory.glob("*.png"))]
        return StaticLayersResponse(layer_assets=assets, report=report)

    return _action(process)


@router.post("/{project_id}/layers/cutout", response_model=StaticLayersResponse)
def cutout_layer(project_id: str, body: StaticLayersRequest) -> StaticLayersResponse:
    info = _load(project_id)

    def process() -> StaticLayersResponse:
        report = static_service.process_layers(info, body.asset, cutout=True)
        return StaticLayersResponse(layer_assets=[_asset_url(project_id, report["output"])], report=report)

    return _action(process)


@router.post("/{project_id}/qa", response_model=StaticQaResponse)
def static_qa(project_id: str, asset: str = "scene") -> StaticQaResponse:
    info = _load(project_id)

    def execute() -> StaticQaResponse:
        report = static_service.static_qa(info, asset)
        return StaticQaResponse(ok=bool(report["ok"]), asset_type=str(report["asset_type"]), warnings=list(report["warnings"]))

    return _action(execute)


@router.post("/{project_id}/export", response_model=StaticExportResponse)
def static_export(project_id: str, asset: str = "scene") -> StaticExportResponse:
    info = _load(project_id)
    return _action(lambda: StaticExportResponse(export_asset=_asset_url(project_id, static_service.export_asset(info, asset))))
