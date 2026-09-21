# SPDX-License-Identifier: Apache-2.0
"""Direct AI C1 Pixel Master generation with the shared logical-grid gate."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from sprite_studio.spec.runio import atomic_save_image, atomic_write_text
from .ai_cleanup import AiPixelMasterCleanupOptions, ai_pixel_master_cleanup
from .logical_grid import validate_and_unzoom


@dataclass(frozen=True)
class C1Options:
    target_size: int = 128
    palette_size: int | None = None
    alpha_threshold: int = 128
    remove_isolated_area: int = 1

    def __post_init__(self) -> None:
        if self.target_size != 128:
            raise ValueError("direct_ai_pixel_master_128 requires target_size=128")


@dataclass(frozen=True)
class C1Result:
    transport_path: Path
    logical_path: Path | None
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


def _prompt(target_size: int) -> str:
    return (
        "Direct C1 generation: design the final character as a true "
        f"{target_size}-logical-pixel game sprite. The character itself must be approximately "
        f"{target_size} logical pixels tall. Do not create a high-resolution illustration that will later be "
        "downscaled. Allocate the logical pixel budget intentionally: enlarge important facial landmarks, group "
        "hair into deliberate pixel clusters, merge tiny costume details into readable shapes, preserve silhouette "
        "and asymmetric identity features, and keep thin identity-defining features at least one logical pixel where "
        "possible. Use hard square pixel clusters, no soft antialiasing, no smooth gradients, and no painterly "
        "micro-detail. If the provider returns a large canvas, render only an INTEGER nearest-neighbor magnification "
        "of the underlying logical sprite. Use a solid magenta background."
    )


def c1_pixel_master_file(
    source_path: Path,
    output_dir: Path,
    *,
    provider: str,
    options: C1Options = C1Options(),
    stem: str = "source",
    workdir: Path | None = None,
) -> C1Result:
    """Generate C1 transport, validate it, and accept only a logical result."""

    if not source_path.is_file():
        raise FileNotFoundError(f"C1 reference image not found: {source_path}")
    output_dir = output_dir.resolve()
    transport_path = output_dir / "transport" / f"{stem}.png"
    logical_path = output_dir / "logical" / f"{stem}.png"
    post_path = output_dir / "post" / f"{stem}.png"
    preview_path = output_dir / "post" / f"{stem}.preview-4x.png"
    palette_path = output_dir / "post" / f"{stem}.palette.json"
    profile_path = output_dir / "post" / f"{stem}.pixel-profile.json"
    report_path = output_dir / "report.json"
    for path in (transport_path, logical_path, post_path):
        path.parent.mkdir(parents=True, exist_ok=True)
    for path in (logical_path, post_path, preview_path, palette_path, profile_path):
        path.unlink(missing_ok=True)

    from studio.backend import provider_service

    generated = provider_service.generate_image(
        provider,
        _prompt(options.target_size),
        transport_path,
        refs=[source_path],
        transparent=True,
        chroma_key="magenta",
        workdir=(workdir or (output_dir / "work")).resolve(),
    )
    with Image.open(transport_path) as opened:
        transport = opened.convert("RGBA")
    validation = validate_and_unzoom(transport, alpha_threshold=options.alpha_threshold)
    base_report = {
        "kind": "sprite-studio-c1-pixel-master",
        "version": 2,
        "strategy": "direct_ai_pixel_master_128",
        "source_reference": str(source_path.resolve()),
        "transport": {"path": str(transport_path), "provider": generated.to_dict(), "size": list(transport.size)},
        "logical_validation": validation.to_dict(),
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
        return C1Result(
            transport_path=transport_path,
            logical_path=None,
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
        "accepted_path": str(post_path),
        "accepted_size": list(cleaned.image.size),
        "warnings": list(validation.warnings) + list(cleaned.warnings),
    }
    atomic_write_text(report_path, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return C1Result(
        transport_path=transport_path,
        logical_path=logical_path,
        post_path=post_path,
        preview_path=preview_path,
        palette_path=palette_path,
        profile_path=profile_path,
        report_path=report_path,
        accepted_path=post_path,
        logical_size=cleaned.image.size,
        palette=cleaned.palette,
        warnings=tuple(report["warnings"]),
        report=report,
        subject_bbox=cleaned.subject_bbox,
    )


__all__ = ["C1Options", "C1Result", "c1_pixel_master_file"]
