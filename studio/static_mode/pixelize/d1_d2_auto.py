# SPDX-License-Identifier: Apache-2.0
"""D1/D2 semantic redraw adapters with identity-preserving Auto Resolution."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from sprite_studio.spec.runio import atomic_save_image, atomic_write_text

from .auto_resolution import AutoResolutionResult, project_auto_resolution
from .d1_d2 import SemanticPseOptions, _d1_prompt, _d2_stage1_prompt, _d2_stage2_prompt
from .identity_manifest import IdentityFeatureManifest
from .identity_review import review_identity_features
from .semantic_pixel_quality import evaluate_semantic_source
from .structure_extractor import PSE_VERSION


@dataclass(frozen=True)
class AutoD1Result:
    semantic_path: Path
    logical_path: Path | None
    preview_path: Path | None
    report_path: Path
    accepted_path: Path | None
    selected_height: int | None
    report: dict[str, Any]


@dataclass(frozen=True)
class AutoD2Result:
    intermediate_path: Path
    semantic_path: Path
    logical_path: Path | None
    preview_path: Path | None
    report_path: Path
    accepted_path: Path | None
    selected_height: int | None
    report: dict[str, Any]


def _paths(output_dir: Path, stem: str) -> tuple[Path, Path, Path, Path]:
    semantic = output_dir / "semantic" / f"{stem}.png"
    logical = output_dir / "logical" / f"{stem}.png"
    preview = output_dir / "logical" / f"{stem}.preview-4x.png"
    report = output_dir / "report.json"
    for path in (semantic, logical, preview, report):
        path.parent.mkdir(parents=True, exist_ok=True)
    logical.unlink(missing_ok=True)
    preview.unlink(missing_ok=True)
    return semantic, logical, preview, report


def _resolution_report(
    *,
    source_path: Path,
    semantic_path: Path,
    semantic_provider: dict[str, Any],
    quality: dict[str, Any],
    resolution: AutoResolutionResult,
    strategy: str,
    intermediate: dict[str, Any] | None = None,
) -> dict[str, Any]:
    with Image.open(semantic_path) as opened:
        semantic_size = list(opened.size)
    report: dict[str, Any] = {
        "kind": "sprite-studio-semantic-auto-resolution",
        "version": 1,
        "strategy": strategy,
        "pse_version": PSE_VERSION,
        "source_reference": str(source_path.resolve()),
        "semantic": {"path": str(semantic_path.resolve()), "provider": semantic_provider, "size": semantic_size},
        "semantic_quality": quality,
        "semantic_preservation": resolution.semantic_preservation.to_dict(),
        "resolution": resolution.to_dict(),
    }
    if intermediate is not None:
        report["intermediate"] = intermediate
    return report


def _run_auto(
    *,
    source_path: Path,
    semantic_path: Path,
    logical_path: Path,
    preview_path: Path,
    report_path: Path,
    semantic_provider: dict[str, Any],
    manifest: IdentityFeatureManifest,
    options: SemanticPseOptions,
    strategy: str,
    intermediate: dict[str, Any] | None = None,
    audit: bool = False,
    override_height: int | None = None,
) -> tuple[Path | None, dict[str, Any], int | None]:
    with Image.open(source_path) as source_opened, Image.open(semantic_path) as semantic_opened:
        source = source_opened.convert("RGBA")
        semantic = semantic_opened.convert("RGBA")
    resolution = project_auto_resolution(
        source,
        semantic,
        manifest,
        palette_size=options.palette_size,
        alpha_threshold=options.alpha_threshold,
        opaque_coverage_threshold=options.opaque_coverage_threshold,
        audit=audit,
        override_height=override_height,
        identity_reviewer=review_identity_features,
    )
    quality = evaluate_semantic_source(semantic, alpha_threshold=options.alpha_threshold).to_dict()
    report = _resolution_report(
        source_path=source_path,
        semantic_path=semantic_path,
        semantic_provider=semantic_provider,
        quality=quality,
        resolution=resolution,
        strategy=strategy,
        intermediate=intermediate,
    )
    accepted: Path | None = None
    if resolution.selected_image is not None and resolution.selected_height is not None:
        atomic_save_image(resolution.selected_image, logical_path)
        atomic_save_image(
            resolution.selected_image.resize((resolution.selected_image.width * 4, resolution.selected_image.height * 4), Image.Resampling.NEAREST),
            preview_path,
        )
        accepted = logical_path
        report["status"] = resolution.status
        report["accepted"] = "logical_master"
        report["accepted_path"] = str(logical_path.resolve())
        report["logical"] = {"path": str(logical_path.resolve()), "size": list(resolution.selected_image.size), "target_height": resolution.selected_height}
    else:
        report["status"] = resolution.status
        report["accepted"] = None
        report["accepted_path"] = None
    if resolution.decision_report.get("resolution_override"):
        identity_passed = bool(resolution.decision_report.get("identity_gate_passed"))
        report["warnings"] = [{
            "code": "identity-resolution-override",
            "message": (
                "Manual resolution override selected a structurally valid master and passed the identity gate."
                if identity_passed else
                "Manual resolution override exported a structurally valid master without passing the identity-preservation gate."
            ),
            "identity_gate_passed": identity_passed,
        }]
    atomic_write_text(report_path, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return accepted, report, resolution.selected_height


def d1_semantic_auto_file(
    source_path: Path,
    output_dir: Path,
    *,
    provider: str,
    manifest: IdentityFeatureManifest,
    options: SemanticPseOptions = SemanticPseOptions(),
    stem: str = "source",
    workdir: Path | None = None,
    audit: bool = False,
) -> AutoD1Result:
    from studio.backend import provider_service

    if provider != "codex":
        raise ValueError("D1 semantic redraw is pinned to GPT Image via the Codex image_gen provider")
    output_dir = output_dir.resolve()
    semantic_path, logical_path, preview_path, report_path = _paths(output_dir, stem)
    generated = provider_service.generate_image(
        provider,
        _d1_prompt(),
        semantic_path,
        refs=[source_path],
        transparent=True,
        chroma_key="magenta",
        workdir=(workdir or output_dir / "work").resolve(),
    )
    provider_record = generated.to_dict()
    provider_record["provider_role"] = "GPT Image semantic Pixel Master redraw"
    provider_record["provider_implementation"] = "Codex built-in image_gen"
    accepted, report, selected_height = _run_auto(
        source_path=source_path,
        semantic_path=semantic_path,
        logical_path=logical_path,
        preview_path=preview_path,
        report_path=report_path,
        semantic_provider=provider_record,
        manifest=manifest,
        options=options,
        strategy="semantic_d1_auto_resolution",
        audit=audit,
    )
    return AutoD1Result(semantic_path, accepted, preview_path if accepted else None, report_path, accepted, selected_height, report)


def d2_semantic_auto_file(
    source_path: Path,
    output_dir: Path,
    *,
    provider: str,
    manifest: IdentityFeatureManifest,
    options: SemanticPseOptions = SemanticPseOptions(),
    stem: str = "source",
    workdir: Path | None = None,
    audit: bool = False,
) -> AutoD2Result:
    from studio.backend import provider_service

    if provider != "codex":
        raise ValueError("D2 semantic redraw is pinned to GPT Image via the Codex image_gen provider")
    output_dir = output_dir.resolve()
    intermediate_path = output_dir / "intermediate" / f"{stem}.png"
    semantic_path, logical_path, preview_path, report_path = _paths(output_dir, stem)
    intermediate_path.parent.mkdir(parents=True, exist_ok=True)
    stage1 = provider_service.generate_image(
        provider,
        _d2_stage1_prompt(),
        intermediate_path,
        refs=[source_path],
        transparent=True,
        chroma_key="magenta",
        workdir=(workdir or output_dir / "work").resolve() / "stage1",
    )
    stage2 = provider_service.generate_image(
        provider,
        _d2_stage2_prompt(),
        semantic_path,
        refs=[source_path, intermediate_path],
        transparent=True,
        chroma_key="magenta",
        workdir=(workdir or output_dir / "work").resolve() / "stage2",
    )
    stage1_record = stage1.to_dict()
    stage1_record["provider_role"] = "GPT Image semantic stage 1"
    stage1_record["provider_implementation"] = "Codex built-in image_gen"
    stage2_record = stage2.to_dict()
    stage2_record["provider_role"] = "GPT Image semantic Pixel Master redraw"
    stage2_record["provider_implementation"] = "Codex built-in image_gen"
    intermediate = {"path": str(intermediate_path.resolve()), "provider": stage1_record}
    accepted, report, selected_height = _run_auto(
        source_path=source_path,
        semantic_path=semantic_path,
        logical_path=logical_path,
        preview_path=preview_path,
        report_path=report_path,
        semantic_provider=stage2_record,
        manifest=manifest,
        options=options,
        strategy="semantic_d2_auto_resolution",
        intermediate=intermediate,
        audit=audit,
    )
    return AutoD2Result(intermediate_path, semantic_path, accepted, preview_path if accepted else None, report_path, accepted, selected_height, report)


__all__ = ["AutoD1Result", "AutoD2Result", "d1_semantic_auto_file", "d2_semantic_auto_file"]
