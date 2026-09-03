# SPDX-License-Identifier: Apache-2.0
"""POST .../generate|normalize|extract|refine — ENDPOINTS.md §"Sprite Mode —
Generate / Normalize / Extract / Refine (single state)".

Every one of these calls into `spritegen_bridge`, which calls into the
`sprite_studio.gen` engine — and that engine raises plain `SystemExit`
pervasively as its fail-loud idiom (`AnchorUnavailable`, `GenTimeoutError`,
`verify_png`, a non-zero provider exit code, `base_source`). `SystemExit` is a
`BaseException`, not an `Exception` — FastAPI/Starlette's default exception
handling does not catch it, so an uncaught one here would not become a clean
500, it would propagate into the ASGI server itself. Every route in this
module catches `SystemExit` explicitly for exactly the reason
`studio.backend.batch_service._execute` now does (the live incident this
directive traces to: a `SystemExit` silently killed a batch worker thread
because only `except Exception` was there to catch it).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from studio.api.contracts import ExtractResponse, GenerateResponse, NormalizeResponse, RefineResponse
from studio.api.deps import asset_url, load_run_and_request, require_state
from studio.backend import qa_service, spritegen_bridge

router = APIRouter(prefix="/runs/{run_id}/states/{state}", tags=["generate"])


def _refine_summary(report: dict[str, Any]) -> str:
    """Locale-neutral port of `studio.app._refine_details` (that version
    renders through the Gradio i18n dict; this API has no locale concept)."""
    if report.get("kind") != "asset-studio-sprite-refine":
        return "legacy refine engine (v1): no lattice report"
    lattice = report["lattice"]
    shared = report["shared"]
    thin = report["thin_feature"]
    clamped = report.get("phase_clamped_frames") or []
    offsets = ", ".join(f"{item['offset'][0]:+.2f}" for item in report["phases"])
    lines = [
        f"Shared Lattice: pitch {lattice['pitch'][0]}x{lattice['pitch'][1]} "
        f"(scope {lattice['scope']}, locked {lattice['locked']})",
        f"Cell-size Confidence: {lattice['confidence'][0]} / {lattice['confidence'][1]}",
        f"Phase Adjustment: offsets {offsets}"
        + (f" (held at bound: frames {clamped})" if clamped else " (none clamped)"),
        f"Thin-feature Protection: {'on' if thin['enabled'] else 'off'}, rescued cells {thin['rescued_cells']}",
        f"Palette Summary: {shared['palette_colors']} colors, "
        f"logical {shared['logical_size'][0]}x{shared['logical_size'][1]}, scale x{shared['scale']}",
    ]
    for warning in report.get("warnings", []):
        lines.append(f"WARNING {warning['code']}: {warning['message']}")
    return "\n".join(lines)


@router.post("/generate", response_model=GenerateResponse)
def generate(run_id: str, state: str) -> GenerateResponse:
    run_dir, request = load_run_and_request(run_id)
    require_state(request, state)
    try:
        report = spritegen_bridge.generate_state(run_dir, state)
    except SystemExit as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except ValueError as exc:
        # prompt validation failure (PromptValidator errors) — a bad
        # override, not a provider/engine failure.
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - fail loud with the real cause, never a bare 500
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}") from exc
    return GenerateResponse(
        provider=report["provider"],
        prompt=report["prompt"],
        raw_asset=asset_url(run_id, run_dir, report["out"]),
        raw_bytes=report["raw_bytes"],
        elapsed_seconds=report["elapsed_seconds"],
        model=report.get("model"),
        refs=[asset_url(run_id, run_dir, ref) for ref in report.get("refs", [])],
        transparent=report["transparent"],
        prompt_source=report["prompt_source"],
    )


@router.post("/normalize", response_model=NormalizeResponse)
def normalize(run_id: str, state: str) -> NormalizeResponse:
    run_dir, request = load_run_and_request(run_id)
    require_state(request, state)
    try:
        report = spritegen_bridge.normalize_state(run_dir, state)
    except spritegen_bridge.NormalizeQualityFailed as exc:
        # An expected quality-gate outcome (Subject Validity / Row-Level
        # Acceptance Gate), not a server error — 422 with the full parsed
        # report so the client can render per-cell reasons the way
        # `batch_service.status_text` already does, not just a string.
        raise HTTPException(status_code=422, detail={"message": str(exc), "report": exc.report}) from exc
    except SystemExit as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}") from exc
    return NormalizeResponse(
        result=report["result"],
        output_asset=asset_url(run_id, run_dir, report["output"]),
        output_size=tuple(report["output_size"]),
        expected_subjects=report["expected_subjects"],
        valid_subjects=report["valid_subjects"],
        report=report,
    )


@router.post("/extract", response_model=ExtractResponse)
def extract(run_id: str, state: str) -> ExtractResponse:
    run_dir, request = load_run_and_request(run_id)
    require_state(request, state)
    try:
        code = spritegen_bridge.extract_frames(run_dir, state)
    except SystemExit as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}") from exc
    return ExtractResponse(exit_code=code, summary=qa_service.summary(run_dir, state))


@router.post("/refine", response_model=RefineResponse)
def refine(run_id: str, state: str) -> RefineResponse:
    run_dir, request = load_run_and_request(run_id)
    require_state(request, state)
    try:
        result = spritegen_bridge.refine_frames(run_dir, state)
    except SystemExit as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except (ValueError, FileNotFoundError) as exc:
        # e.g. "extract first: frames-manifest.json is missing" — an
        # ordering mistake by the caller, not a server error.
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}") from exc
    preview = asset_url(run_id, run_dir, result.output_files[0]) if result.output_files else None
    return RefineResponse(refined_preview_asset=preview, report=result.report, summary=_refine_summary(result.report))
