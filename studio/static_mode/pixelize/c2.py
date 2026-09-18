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


@dataclass(frozen=True)
class C2Options:
    target_size: int = 128
    palette_size: int | None = None
    alpha_threshold: int = 128
    remove_isolated_area: int = 1

    def __post_init__(self) -> None:
        if self.target_size != 128:
            raise ValueError("reference_pixel_master_128 requires target_size=128")


@dataclass(frozen=True)
class C2Result:
    raw_path: Path
    intermediate_path: Path
    post_path: Path
    preview_path: Path
    palette_path: Path
    profile_path: Path
    report_path: Path
    accepted_path: Path
    logical_size: tuple[int, int]
    palette: tuple[tuple[int, int, int, int], ...]
    warnings: tuple[dict[str, Any], ...]
    report: dict[str, Any]
    subject_bbox: tuple[int, int, int, int]


def _stage1_prompt(target_size: int) -> str:
    return (
        "Reference-guided C2 stage 1: translate the supplied character reference into a clear authored pixel-art style. "
        f"Keep the exact character identity, pose, silhouette, face, hair, costume, weapon and asymmetric details. "
        f"Prepare a high-resolution pixel-style intermediate for a {target_size}px final redraw; use crisp clusters, "
        "flat readable regions, no text, no UI, no extra characters, and a solid magenta background for reliable removal."
    )


def _stage2_prompt(target_size: int) -> str:
    return (
        "Reference-guided C2 stage 2: redraw the supplied pixel-style intermediate into a production-ready logical "
        f"{target_size}px pixel master. Preserve the original reference identity and the intermediate's intentional "
        "pixel clusters, face readability, silhouette, costume hierarchy, weapon/accessory details, and asymmetry. "
        "Do not blur, smooth, thicken outlines, add text, or redesign the character. Use a solid magenta background."
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
    raw_path = output_dir / "raw" / f"{stem}.png"
    post_path = output_dir / "post" / f"{stem}.png"
    preview_path = output_dir / "post" / f"{stem}.preview-4x.png"
    palette_path = output_dir / "post" / f"{stem}.palette.json"
    profile_path = output_dir / "post" / f"{stem}.pixel-profile.json"
    report_path = output_dir / "report.json"
    stage_workdir = (workdir or (output_dir / "work")).resolve()
    intermediate_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    post_path.parent.mkdir(parents=True, exist_ok=True)

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
    cleaned = ai_pixel_master_cleanup(
        raw,
        AiPixelMasterCleanupOptions(
            target_size=options.target_size,
            palette_size=options.palette_size,
            alpha_threshold=options.alpha_threshold,
            remove_isolated_area=options.remove_isolated_area,
        ),
    )
    atomic_save_image(cleaned.image, post_path)
    atomic_save_image(
        cleaned.image.resize((cleaned.image.width * 4, cleaned.image.height * 4), Image.Resampling.NEAREST),
        preview_path,
    )
    atomic_write_text(palette_path, json.dumps({"kind": "sprite-studio-pixel-palette", "entries": [list(entry) for entry in cleaned.palette]}, ensure_ascii=False, indent=2) + "\n")
    atomic_write_text(profile_path, json.dumps(cleaned.report.get("scale", {}), ensure_ascii=False, indent=2) + "\n")
    report = {
        "kind": "sprite-studio-c2-pixel-master",
        "version": 1,
        "strategy": "reference_pixel_master_128",
        "source_reference": str(source_path.resolve()),
        "intermediate": {"path": str(intermediate_path), "provider": stage1.to_dict()},
        "raw": {"path": str(raw_path), "provider": stage2.to_dict()},
        "post": {"path": str(post_path), "preview": str(preview_path), "palette": str(palette_path), "profile": str(profile_path), "cleanup": cleaned.report},
        "accepted": "post",
        "warnings": list(cleaned.warnings),
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
        accepted_path=post_path,
        logical_size=cleaned.image.size,
        palette=cleaned.palette,
        warnings=cleaned.warnings,
        report=report,
        subject_bbox=cleaned.subject_bbox,
    )


__all__ = ["C2Options", "C2Result", "c2_pixel_master_file"]
