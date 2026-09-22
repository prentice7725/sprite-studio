# SPDX-License-Identifier: Apache-2.0
"""Production-oriented D1/D2 semantic redraw plus PSE adapters."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from sprite_studio.spec.runio import atomic_save_image, atomic_write_text

from .ai_cleanup import AiPixelMasterCleanupOptions, ai_pixel_master_cleanup
from .semantic_pixel_quality import evaluate_semantic_source
from .resolution import require_logical_height
from .structure_extractor import (
    PSE_VERSION,
    StructureExtractorOptions,
    extract_structure,
    validate_logical_master,
)


@dataclass(frozen=True)
class SemanticPseOptions:
    target_size: int = 128
    palette_size: int | None = 48
    alpha_threshold: int = 128
    opaque_coverage_threshold: float = 0.18

    def __post_init__(self) -> None:
        require_logical_height(self.target_size, field_name="target_size")
        if self.palette_size is not None and self.palette_size not in {24, 32, 48}:
            raise ValueError("palette_size must be auto/None or one of 24, 32, 48")


@dataclass(frozen=True)
class D1Result:
    semantic_path: Path
    logical_path: Path | None
    preview_path: Path | None
    palette_path: Path | None
    report_path: Path
    accepted_path: Path | None
    report: dict[str, Any]


@dataclass(frozen=True)
class D2Result:
    intermediate_path: Path
    semantic_path: Path
    logical_path: Path | None
    preview_path: Path | None
    palette_path: Path | None
    report_path: Path
    accepted_path: Path | None
    report: dict[str, Any]


def _d1_prompt() -> str:
    return (
        "Preserve the exact identity of the attached character. Redraw the character in a deliberately "
        "low-resolution pixel-art design language. Do not merely apply a pixel filter. Reallocate visual "
        "information for small-scale readability. Simplify hair into clear intentional masses and clusters. "
        "Keep the eyes, brows, nose, mouth and jaw readable with fewer larger shapes. Merge tiny costume details "
        "into larger readable motifs. Preserve asymmetric identity details. Use flat coherent color regions, crisp "
        "block-like contours and stepped shading. Avoid painterly texture, soft gradients, blur, bloom and "
        "micro-detail. The result may be high resolution; its purpose is to provide semantically simplified "
        "pixel-art structure for deterministic projection into a 128/160/192/256 logical-pixel master. Use a solid magenta "
        "background and no text, UI, or extra characters."
    )


def _d2_stage1_prompt() -> str:
    return (
        "Translate the attached character into a clear authored pixel-art design language while preserving exact "
        "identity, pose, silhouette, face, hair, costume, weapon and asymmetric details. Simplify hair into "
        "intentional masses, group facial landmarks into readable shapes, merge tiny costume details into larger "
        "motifs, and use flat coherent color regions with crisp stepped contours. This is a high-resolution "
        "semantic intermediate; do not require an exact logical grid yet. Avoid painterly texture, blur, bloom, "
        "soft gradients, text, UI, and extra characters. Use a solid magenta background."
    )


def _d2_stage2_prompt() -> str:
    return (
        "Using the original character reference and the stage-1 semantic pixel-art intermediate, redraw a compact "
        "pixel-art design intended to survive projection to one of 128, 160, 192, or 256 logical pixels of character height. "
        "Spend visual detail only on identity-critical features. Increase the relative size of eyes and facial "
        "landmarks when necessary. Merge only regions that would disappear at the selected logical resolution. Keep thin identity-defining "
        "equipment visually separable. Preserve silhouette, asymmetric identity details and readable costume "
        "hierarchy. Do not merely apply a pixel filter, and do not require an exact logical grid or integer transport. "
        "Avoid painterly texture, soft gradients, blur, bloom, text, UI, and extra characters. Use a solid magenta "
        "background."
    )


def _paths(output_dir: Path, stem: str) -> tuple[Path, Path, Path, Path, Path]:
    semantic = output_dir / "semantic" / f"{stem}.png"
    logical = output_dir / "logical" / f"{stem}.png"
    preview = output_dir / "logical" / f"{stem}.preview-4x.png"
    palette = output_dir / "logical" / f"{stem}.palette.json"
    report = output_dir / "report.json"
    for path in (semantic, logical, preview, palette, report):
        path.parent.mkdir(parents=True, exist_ok=True)
    for path in (logical, preview, palette):
        path.unlink(missing_ok=True)
    return semantic, logical, preview, palette, report


def _finalize(
    *,
    source_path: Path,
    semantic_path: Path,
    logical_path: Path,
    preview_path: Path,
    palette_path: Path,
    report_path: Path,
    strategy: str,
    semantic_provider: dict[str, Any],
    options: SemanticPseOptions,
    intermediate: dict[str, Any] | None = None,
) -> tuple[Path | None, dict[str, Any]]:
    with Image.open(semantic_path) as opened:
        semantic = opened.convert("RGBA")
    quality = evaluate_semantic_source(semantic, alpha_threshold=options.alpha_threshold)
    base_report: dict[str, Any] = {
        "kind": "sprite-studio-semantic-pse",
        "version": 1,
        "strategy": strategy,
        "pse_version": PSE_VERSION,
        "source_reference": str(source_path.resolve()),
        "semantic": {"path": str(semantic_path), "provider": semantic_provider, "size": list(semantic.size)},
        "semantic_quality": quality.to_dict(),
    }
    if intermediate is not None:
        base_report["intermediate"] = intermediate
    if not quality.passed:
        report = {**base_report, "status": quality.status, "accepted": None, "accepted_path": None, "pse": None, "logical_validation": None}
        atomic_write_text(report_path, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        return None, report

    extracted = extract_structure(
        semantic,
        StructureExtractorOptions(
            target_height=options.target_size,
            palette_size=options.palette_size,
            alpha_threshold=options.alpha_threshold,
            opaque_coverage_threshold=options.opaque_coverage_threshold,
        ),
    )
    if extracted.image is None:
        report = {**base_report, "status": extracted.report.get("status", "FAIL_PSE"), "accepted": None, "accepted_path": None, "pse": extracted.report, "logical_validation": None}
        atomic_write_text(report_path, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        return None, report

    pre_cleanup_size = extracted.image.size
    cleanup = ai_pixel_master_cleanup(
        extracted.image,
        AiPixelMasterCleanupOptions(
            target_size=options.target_size,
            palette_size=None,
            alpha_threshold=options.alpha_threshold,
            geometry_resize=False,
            remove_background=False,
            remove_isolated_area=0,
        ),
    )
    cleanup_mutated_dimensions = cleanup.image.size != pre_cleanup_size
    validation = validate_logical_master(
        cleanup.image,
        target_height=options.target_size,
        alpha_threshold=options.alpha_threshold,
        max_palette_size=options.palette_size,
    )
    validation_metrics = dict(validation.metrics)
    validation_metrics["cleanup_mutated_dimensions"] = cleanup_mutated_dimensions
    if cleanup_mutated_dimensions:
        validation = type(validation)(
            False,
            "FAIL_IMPLEMENTATION_DIMENSION_MUTATION",
            validation_metrics,
            tuple(validation.warnings) + ({"code": "cleanup-mutated-dimensions", "message": "Cleanup changed the selected logical dimensions."},),
        )
    if not validation.pass_:
        report = {
            **base_report,
            "status": "FAIL_LOGICAL_MASTER",
            "accepted": None,
            "accepted_path": None,
            "pse": extracted.report,
            "cleanup": cleanup.report,
            "logical_validation": validation.to_dict(),
        }
        atomic_write_text(report_path, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        return None, report

    atomic_save_image(cleanup.image, logical_path)
    atomic_save_image(
        cleanup.image.resize((cleanup.image.width * 4, cleanup.image.height * 4), Image.Resampling.NEAREST),
        preview_path,
    )
    atomic_write_text(
        palette_path,
        json.dumps({"kind": "sprite-studio-pse-palette", "entries": [list(entry) for entry in extracted.palette]}, ensure_ascii=False, indent=2) + "\n",
    )
    report = {
        **base_report,
        "status": "PASS_LOGICAL_MASTER",
        "pse": extracted.report,
        "cleanup": cleanup.report,
        "logical": {"path": str(logical_path), "size": list(cleanup.image.size)},
        "preview": {"path": str(preview_path), "scale": 4, "resampling": "nearest"},
        "palette": {"path": str(palette_path), "colors": len(extracted.palette)},
        "logical_validation": validation.to_dict(),
        "accepted": "logical_post",
        "accepted_path": str(logical_path),
    }
    atomic_write_text(report_path, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return logical_path, report


def d1_semantic_pse_file(
    source_path: Path,
    output_dir: Path,
    *,
    provider: str,
    options: SemanticPseOptions = SemanticPseOptions(),
    stem: str = "source",
    workdir: Path | None = None,
) -> D1Result:
    if not source_path.is_file():
        raise FileNotFoundError(f"D1 reference image not found: {source_path}")
    output_dir = output_dir.resolve()
    semantic_path, logical_path, preview_path, palette_path, report_path = _paths(output_dir, stem)
    from studio.backend import provider_service

    generated = provider_service.generate_image(
        provider,
        _d1_prompt(),
        semantic_path,
        refs=[source_path],
        transparent=True,
        chroma_key="magenta",
        workdir=(workdir or output_dir / "work").resolve(),
    )
    accepted, report = _finalize(
        source_path=source_path,
        semantic_path=semantic_path,
        logical_path=logical_path,
        preview_path=preview_path,
        palette_path=palette_path,
        report_path=report_path,
        strategy="semantic_d1_pse",
        semantic_provider=generated.to_dict(),
        options=options,
    )
    return D1Result(semantic_path, accepted, preview_path if accepted else None, palette_path if accepted else None, report_path, accepted, report)


def d2_semantic_pse_file(
    source_path: Path,
    output_dir: Path,
    *,
    provider: str,
    options: SemanticPseOptions = SemanticPseOptions(),
    stem: str = "source",
    workdir: Path | None = None,
) -> D2Result:
    if not source_path.is_file():
        raise FileNotFoundError(f"D2 reference image not found: {source_path}")
    output_dir = output_dir.resolve()
    intermediate_path = output_dir / "intermediate" / f"{stem}.png"
    semantic_path, logical_path, preview_path, palette_path, report_path = _paths(output_dir, stem)
    intermediate_path.parent.mkdir(parents=True, exist_ok=True)
    intermediate_path.unlink(missing_ok=True)
    from studio.backend import provider_service

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
    accepted, report = _finalize(
        source_path=source_path,
        semantic_path=semantic_path,
        logical_path=logical_path,
        preview_path=preview_path,
        palette_path=palette_path,
        report_path=report_path,
        strategy="semantic_d2_pse",
        semantic_provider=stage2.to_dict(),
        options=options,
        intermediate={"path": str(intermediate_path), "provider": stage1.to_dict()},
    )
    return D2Result(intermediate_path, semantic_path, accepted, preview_path if accepted else None, palette_path if accepted else None, report_path, accepted, report)


__all__ = [
    "D1Result",
    "D2Result",
    "SemanticPseOptions",
    "d1_semantic_pse_file",
    "d2_semantic_pse_file",
]
