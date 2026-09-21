# SPDX-License-Identifier: Apache-2.0
"""Reference-guided C2: AI pixel-style translation followed by 128px redraw."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from sprite_studio.spec.runio import atomic_save_image, atomic_write_text
from .ai_cleanup import AiPixelMasterCleanupOptions, ai_pixel_master_cleanup
from .logical_grid import LogicalGridResult, validate_and_unzoom


@dataclass(frozen=True)
class C2Options:
    target_size: int = 128
    palette_size: int | None = None
    alpha_threshold: int = 128
    remove_isolated_area: int = 1
    # ``post`` remains the API spelling for compatibility; it now means the
    # post-cleanup logical master, never the raw transport image.
    accepted: str = "post"

    def __post_init__(self) -> None:
        if self.target_size != 128:
            raise ValueError("reference_pixel_master_128 requires target_size=128")
        if self.accepted not in {"post", "logical_post"}:
            raise ValueError("accepted must be post or logical_post; raw transport cannot be accepted")


@dataclass(frozen=True)
class C2Result:
    raw_path: Path
    intermediate_path: Path
    post_path: Path | None
    preview_path: Path | None
    palette_path: Path | None
    profile_path: Path | None
    report_path: Path
    accepted_path: Path | None
    logical_size: tuple[int, int] | None
    palette: tuple[tuple[int, int, int, int], ...]
    warnings: tuple[dict[str, Any], ...]
    report: dict[str, Any]
    subject_bbox: tuple[int, int, int, int]
    logical_path: Path | None = None

    @property
    def transport_path(self) -> Path:
        """Return the stage-2 transport path (raw_path is a compatibility alias)."""

        return self.raw_path


def _stage1_prompt(target_size: int) -> str:
    return (
        "Reference-guided C2 stage 1: translate the supplied character reference into a clear authored pixel-art style. "
        f"Keep the exact character identity, pose, silhouette, face, hair, costume, weapon and asymmetric details. "
        f"Prepare a high-resolution pixel-style intermediate for a {target_size}px final redraw; use intentional hair "
        "clusters, readable face landmarks, flat readable regions, and a coherent limited-palette hierarchy. "
        "Preserve thin important equipment as at least a readable 1px feature at final size, while merging tiny "
        "costume details into readable patterns. Do not add text, UI, or extra characters, and use a solid magenta "
        "background for reliable removal."
    )


def _stage2_prompt(target_size: int) -> str:
    return (
        "Reference-guided C2 stage 2: redraw the supplied pixel-style intermediate into a production-ready logical "
        f"{target_size}px pixel master. Preserve the original reference identity and the intermediate's intentional "
        "pixel clusters, face readability, silhouette, costume hierarchy, weapon/accessory details, and asymmetry. "
        "At 128px, redistribute tiny eyes and facial landmarks when necessary for readability instead of shrinking "
        "high-resolution geometry literally. Simplify hair into intentional clusters, merge tiny costume details "
        "into readable patterns, and preserve important thin equipment as at least a readable 1px feature. Do not "
        "blur, smooth, thicken outlines, add text, or redesign the character. Avoid painterly gradients and soft "
        "brush texture; use crisp authored pixel clusters. If the provider returns a larger canvas, it must be a "
        "pure INTEGER nearest-neighbor magnification of the underlying logical sprite, never a high-resolution "
        "illustration intended for later downscaling. Use a solid magenta background."
    )


def c2_pixel_master_file(
    source_path: Path,
    output_dir: Path,
    *,
    provider: str,
    options: C2Options = C2Options(),
    stem: str = "source",
    workdir: Path | None = None,
) -> C2Result:
    """Run C2 with explicit source reference and auditable intermediate/raw/post files.

    There is deliberately no deterministic fallback: a C2 request either runs
    both provider stages or fails loudly.
    """

    if not source_path.is_file():
        raise FileNotFoundError(f"C2 reference image not found: {source_path}")
    output_dir = output_dir.resolve()
    intermediate_path = output_dir / "intermediate" / f"{stem}.png"
    raw_path = output_dir / "raw" / f"{stem}.png"  # compatibility alias for transport
    logical_path = output_dir / "logical" / f"{stem}.png"
    post_path = output_dir / "post" / f"{stem}.png"
    preview_path = output_dir / "post" / f"{stem}.preview-4x.png"
    palette_path = output_dir / "post" / f"{stem}.palette.json"
    profile_path = output_dir / "post" / f"{stem}.pixel-profile.json"
    report_path = output_dir / "report.json"
    stage_workdir = (workdir or (output_dir / "work")).resolve()
    for path in (intermediate_path, raw_path, logical_path, post_path):
        path.parent.mkdir(parents=True, exist_ok=True)
    for path in (logical_path, post_path, preview_path, palette_path, profile_path):
        path.unlink(missing_ok=True)

    from studio.backend import provider_service

    stage1 = provider_service.generate_image(
        provider,
        _stage1_prompt(options.target_size),
        intermediate_path,
        refs=[source_path],
        transparent=True,
        chroma_key="magenta",
        workdir=stage_workdir / "stage1",
    )
    stage2 = provider_service.generate_image(
        provider,
        _stage2_prompt(options.target_size),
        raw_path,
        refs=[source_path, intermediate_path],
        transparent=True,
        chroma_key="magenta",
        workdir=stage_workdir / "stage2",
    )
    with Image.open(raw_path) as opened:
        raw = opened.convert("RGBA")
    validation = validate_and_unzoom(raw, alpha_threshold=options.alpha_threshold)
    validation_report = validation.to_dict()
    base_report = {
        "kind": "sprite-studio-c2-pixel-master",
        "version": 2,
        "strategy": "reference_pixel_master_128",
        "source_reference": str(source_path.resolve()),
        "intermediate": {"path": str(intermediate_path), "provider": stage1.to_dict()},
        "transport": {"path": str(raw_path), "provider": stage2.to_dict(), "size": list(raw.size)},
        # Retain the old key as an audit alias; it is never an accepted path.
        "raw": {"path": str(raw_path), "provider": stage2.to_dict()},
        "logical_validation": validation_report,
    }
    if not validation.pass_ or validation.logical_image is None:
        report = {
            **base_report,
            "status": "FAIL_LOGICAL_GRID",
            "logical": None,
            "cleanup": None,
            "accepted": None,
            "accepted_path": None,
            "accepted_size": None,
            "warnings": list(validation.warnings),
        }
        atomic_write_text(report_path, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        return C2Result(
            raw_path=raw_path,
            intermediate_path=intermediate_path,
            post_path=None,
            preview_path=None,
            palette_path=None,
            profile_path=None,
            report_path=report_path,
            accepted_path=None,
            logical_size=None,
            palette=(),
            warnings=validation.warnings,
            report=report,
            subject_bbox=(0, 0, 0, 0),
            logical_path=None,
        )

    logical = validation.logical_image
    atomic_save_image(logical, logical_path)
    cleaned = ai_pixel_master_cleanup(
        logical,
        AiPixelMasterCleanupOptions(
            target_size=options.target_size,
            palette_size=options.palette_size,
            alpha_threshold=options.alpha_threshold,
            remove_isolated_area=options.remove_isolated_area,
            geometry_resize=False,
        ),
    )
    atomic_save_image(cleaned.image, post_path)
    atomic_save_image(
        cleaned.image.resize((cleaned.image.width * 4, cleaned.image.height * 4), Image.Resampling.NEAREST),
        preview_path,
    )
    atomic_write_text(
        palette_path,
        json.dumps(
            {"kind": "sprite-studio-pixel-palette", "entries": [list(entry) for entry in cleaned.palette]},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
    )
    atomic_write_text(
        profile_path,
        json.dumps(cleaned.report.get("scale", {}), ensure_ascii=False, indent=2) + "\n",
    )
    accepted_path = post_path
    accepted_size = cleaned.image.size
    report = {
        **base_report,
        "status": "PASS",
        "logical": {"path": str(logical_path), "size": list(logical.size)},
        "post": {
            "path": str(post_path),
            "preview": str(preview_path),
            "palette": str(palette_path),
            "profile": str(profile_path),
        },
        "cleanup": cleaned.report,
        "accepted": "logical_post",
        "accepted_requested": options.accepted,
        "accepted_path": str(accepted_path),
        "accepted_size": list(accepted_size),
        "warnings": list(validation.warnings) + list(cleaned.warnings),
    }
    atomic_write_text(report_path, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return C2Result(
        raw_path=raw_path,
        intermediate_path=intermediate_path,
        post_path=post_path,
        preview_path=preview_path,
        palette_path=palette_path,
        profile_path=profile_path,
        report_path=report_path,
        accepted_path=accepted_path,
        logical_size=accepted_size,
        palette=cleaned.palette,
        warnings=tuple(report["warnings"]),
        report=report,
        subject_bbox=cleaned.subject_bbox,
        logical_path=logical_path,
    )


__all__ = ["C2Options", "C2Result", "c2_pixel_master_file"]
