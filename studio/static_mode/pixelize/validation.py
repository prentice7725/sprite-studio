# SPDX-License-Identifier: Apache-2.0
"""Acceptance validation for deterministic Pixelize logical masters."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from .resolution import require_logical_height


@dataclass(frozen=True)
class PixelMasterValidation:
    pass_: bool
    status: str
    metrics: dict[str, Any]
    warnings: tuple[dict[str, str], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "pass": self.pass_,
            "status": self.status,
            "metrics": self.metrics,
            "warnings": list(self.warnings),
        }


class PixelMasterValidationError(ValueError):
    def __init__(self, validation: PixelMasterValidation):
        self.validation = validation
        codes = ", ".join(str(warning["code"]) for warning in validation.warnings)
        super().__init__(f"logical Pixel Master validation failed: {validation.status} ({codes})")


def validate_deterministic_pixel_master(
    image: Image.Image,
    palette: tuple[tuple[int, int, int, int], ...],
    *,
    target_height: int,
    alpha_threshold: int,
    max_palette_size: int,
) -> PixelMasterValidation:
    """Check the logical geometry, alpha, and palette invariants in one place."""
    require_logical_height(target_height)
    if not 1 <= alpha_threshold <= 254:
        raise ValueError("alpha_threshold must be between 1 and 254")

    rgba = image.convert("RGBA")
    array = np.asarray(rgba, dtype=np.uint8)
    alpha = array[:, :, 3]
    opaque = alpha >= alpha_threshold
    ys, xs = np.where(opaque)
    bbox = None if not len(xs) else [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1]
    subject_height = 0 if bbox is None else bbox[3] - bbox[1]
    alpha_values = {int(value) for value in np.unique(alpha)}
    binary_alpha = alpha_values <= {0, 255}
    output_colors = {tuple(int(channel) for channel in pixel) for pixel in array[opaque, :3]}
    palette_colors = {tuple(int(channel) for channel in color[:3]) for color in palette}
    palette_size = len(output_colors)
    colors_in_palette = output_colors <= palette_colors

    warnings: list[dict[str, str]] = []
    if rgba.width <= 0 or rgba.height != target_height:
        warnings.append({"code": "logical-size-invalid", "message": f"Logical canvas is {rgba.width}×{rgba.height}; expected positive width and height {target_height}."})
    if bbox is None or subject_height != target_height:
        warnings.append({"code": "subject-height-invalid", "message": f"Logical subject height is {subject_height}; expected {target_height}."})
    if not binary_alpha:
        warnings.append({"code": "alpha-invalid", "message": "Logical master alpha must contain only 0 and 255."})
    if not palette_size:
        warnings.append({"code": "subject-empty", "message": "Logical master contains no opaque subject pixels."})
    if palette_size > max_palette_size:
        warnings.append({"code": "palette-limit-exceeded", "message": f"Logical master has {palette_size} colors; limit is {max_palette_size}."})
    if not colors_in_palette:
        warnings.append({"code": "palette-membership-invalid", "message": "Logical master contains a color absent from its declared palette."})

    passed = (
        rgba.width > 0
        and rgba.height == target_height
        and bbox is not None
        and subject_height == target_height
        and binary_alpha
        and bool(palette_size)
        and palette_size <= max_palette_size
        and colors_in_palette
    )
    return PixelMasterValidation(
        passed,
        "PASS_LOGICAL_MASTER" if passed else "FAIL_LOGICAL_MASTER",
        {
            "logical_size": [rgba.width, rgba.height],
            "subject_bbox": bbox,
            "subject_height": subject_height,
            "target_height": target_height,
            "binary_alpha": binary_alpha,
            "alpha_values": sorted(alpha_values),
            "palette_size": palette_size,
            "max_palette_size": max_palette_size,
            "colors_in_palette": colors_in_palette,
        },
        tuple(warnings),
    )


def _read_png(path: Path) -> Image.Image | None:
    try:
        with Image.open(path) as opened:
            if opened.format != "PNG":
                return None
            opened.verify()
        with Image.open(path) as opened:
            return opened.convert("RGBA")
    except (OSError, ValueError):
        return None


def validate_pixelize_artifacts(
    logical: Image.Image,
    palette: tuple[tuple[int, int, int, int], ...],
    *,
    target_height: int,
    alpha_threshold: int,
    max_palette_size: int,
    output_path: Path,
    preview_path: Path,
    subject_path: Path,
    preview_scale: int = 4,
) -> PixelMasterValidation:
    """Validate the logical master and the PNG artifacts emitted for it."""
    base = validate_deterministic_pixel_master(
        logical,
        palette,
        target_height=target_height,
        alpha_threshold=alpha_threshold,
        max_palette_size=max_palette_size,
    )
    expected_logical = np.asarray(logical.convert("RGBA"), dtype=np.uint8)
    output = _read_png(output_path)
    preview = _read_png(preview_path)
    subject = _read_png(subject_path)
    expected_preview = np.asarray(
        logical.convert("RGBA").resize(
            (logical.width * preview_scale, logical.height * preview_scale),
            Image.Resampling.NEAREST,
        ),
        dtype=np.uint8,
    )
    output_matches = output is not None and np.array_equal(np.asarray(output, dtype=np.uint8), expected_logical)
    preview_matches = preview is not None and np.array_equal(np.asarray(preview, dtype=np.uint8), expected_preview)
    warnings = list(base.warnings)
    if output is None:
        warnings.append({"code": "output-png-invalid", "message": "Logical master output is missing or is not a readable PNG."})
    elif not output_matches:
        warnings.append({"code": "output-png-mismatch", "message": "Saved logical master differs from the validated in-memory image."})
    if preview is None:
        warnings.append({"code": "preview-png-invalid", "message": "Preview is missing or is not a readable PNG."})
    elif not preview_matches:
        warnings.append({"code": "preview-mismatch", "message": f"Preview is not an exact {preview_scale}× NEAREST enlargement of the logical master."})
    if subject is None:
        warnings.append({"code": "subject-png-invalid", "message": "Saved subject crop is missing or is not a readable PNG."})

    passed = base.pass_ and output_matches and preview_matches and subject is not None
    metrics = {
        **base.metrics,
        "output_png_valid": output is not None,
        "preview_png_valid": preview is not None,
        "subject_png_valid": subject is not None,
        "output_matches_logical": bool(output_matches),
        "preview_matches_nearest": bool(preview_matches),
        "preview_scale": preview_scale,
    }
    return PixelMasterValidation(
        passed,
        "PASS_LOGICAL_MASTER" if passed else "FAIL_LOGICAL_MASTER",
        metrics,
        tuple(warnings),
    )
