# SPDX-License-Identifier: Apache-2.0
"""Illustration -> logical pixel master conversion.

Pixelize is intentionally different from Static Refine's grid recovery. Refine
tries to discover a pixel lattice that is already present in a generated raster;
Pixelize is given a smooth/high-resolution illustration and an explicit logical
resolution. It therefore owns the target grid and makes one deterministic color
decision per logical pixel.

The important ordering is:

    source RGBA
      -> alpha normalization
      -> one shared Oklab palette
      -> palette-map in source space
      -> dominant-cell sampling onto the declared logical grid
      -> optional ordered dither on the logical image

This avoids average-color downsampling, which invents fringe colors at edges and
is the main source of the "small smooth illustration" look that Pixelize exists
to avoid.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

import numpy as np
from PIL import Image

from sprite_studio.spec.runio import atomic_save_image, atomic_write_text
from studio.shared.config import DitherSettings
from studio.shared.palette import apply_palette, build_palette, palette_distance_report
from studio.static_mode.refine.dither import apply_dither


SUPPORTED_SIZES = (64, 96, 128, 192)
SUPPORTED_PALETTES = (16, 24, 32, 48)
DitherMode = Literal["none", "ordered-low", "ordered"]
BackgroundMode = Literal["keep", "cleanup"]
OutlineMode = Literal["preserve", "auto"]


@dataclass(frozen=True)
class PixelizeOptions:
    """Stable, serializable Pixelize M1 contract."""

    target_size: int = 128
    palette_size: int | None = 32
    dither: DitherMode = "none"
    background: BackgroundMode = "keep"
    outline: OutlineMode = "preserve"
    alpha_threshold: int = 128

    def __post_init__(self) -> None:
        if self.target_size not in SUPPORTED_SIZES:
            raise ValueError(f"target_size must be one of {SUPPORTED_SIZES}, got {self.target_size}")
        if self.palette_size is not None and self.palette_size not in SUPPORTED_PALETTES:
            raise ValueError(f"palette_size must be auto/None or one of {SUPPORTED_PALETTES}")
        if self.dither not in {"none", "ordered-low", "ordered"}:
            raise ValueError("dither must be none, ordered-low, or ordered")
        if self.background not in {"keep", "cleanup"}:
            raise ValueError("background must be keep or cleanup")
        if self.outline not in {"preserve", "auto"}:
            raise ValueError("outline must be preserve or auto")
        if not (1 <= self.alpha_threshold <= 254):
            raise ValueError("alpha_threshold must be between 1 and 254")


@dataclass(frozen=True)
class PixelizeResult:
    output_path: Path
    palette_path: Path
    profile_path: Path
    report_path: Path
    preview_path: Path
    logical_size: tuple[int, int]
    palette: tuple[tuple[int, int, int, int], ...]
    warnings: tuple[dict[str, Any], ...]
    report: dict[str, Any]


def _logical_size(source_size: tuple[int, int], target: int) -> tuple[int, int]:
    width, height = source_size
    if width <= 0 or height <= 0:
        raise ValueError(f"source image has invalid size {source_size}")
    if width >= height:
        return target, max(1, int(round(height * target / width)))
    return max(1, int(round(width * target / height))), target


def _normalise_alpha(image: Image.Image, options: PixelizeOptions) -> tuple[Image.Image, list[dict[str, Any]]]:
    source = np.asarray(image.convert("RGBA"), dtype=np.uint8).copy()
    warnings: list[dict[str, Any]] = []
    alpha = source[:, :, 3]
    had_partial_alpha = bool(np.any((alpha > 0) & (alpha < 255)))
    had_transparency = bool(np.any(alpha < 255))

    if options.background == "cleanup":
        if not had_transparency:
            warnings.append({
                "code": "cleanup-no-alpha",
                "message": "background cleanup only normalizes an existing alpha mask in M1; the source is fully opaque",
            })
        source[:, :, 3] = np.where(alpha >= options.alpha_threshold, 255, 0).astype(np.uint8)
    elif had_partial_alpha:
        # Keep mode preserves source alpha. Palette mapping still considers pixels
        # opaque from alpha_threshold upward, but the report makes the source state
        # explicit so a later video-frame profile can choose cleanup deliberately.
        warnings.append({
            "code": "partial-alpha-kept",
            "message": "source contains partial alpha and background=keep preserved it until palette mapping",
        })

    transparent = source[:, :, 3] < options.alpha_threshold
    source[transparent, :3] = 0
    if options.background == "cleanup":
        source[transparent, 3] = 0
    return Image.fromarray(source, mode="RGBA"), warnings


def _auto_palette_size(image: Image.Image, alpha_threshold: int) -> int:
    array = np.asarray(image.convert("RGBA"), dtype=np.uint8).reshape(-1, 4)
    opaque = array[array[:, 3] >= alpha_threshold]
    if opaque.size == 0:
        return 16
    unique = int(np.unique(opaque[:, :3], axis=0).shape[0])
    if unique <= 32:
        return 16
    if unique <= 128:
        return 24
    if unique <= 768:
        return 32
    return 48


def _dominant_downsample(
    mapped: Image.Image,
    palette: tuple[tuple[int, int, int, int], ...],
    size: tuple[int, int],
    *,
    outline: OutlineMode,
    alpha_threshold: int,
) -> Image.Image:
    """Pick one existing palette color per logical cell; never average colors."""
    source = np.asarray(mapped.convert("RGBA"), dtype=np.uint8)
    src_h, src_w, _ = source.shape
    out_w, out_h = size
    result = np.zeros((out_h, out_w, 4), dtype=np.uint8)

    # Luma ranks let outline preservation prefer an existing dark palette entry
    # only when it already occupies a meaningful share of a cell. It never
    # invents a new outline color.
    palette_rgb = np.asarray([entry[:3] for entry in palette], dtype=np.float64) if palette else np.zeros((0, 3))
    palette_luma = 0.2126 * palette_rgb[:, 0] + 0.7152 * palette_rgb[:, 1] + 0.0722 * palette_rgb[:, 2]
    dark_cutoff = float(np.quantile(palette_luma, 0.30)) if len(palette_luma) else 0.0

    for oy in range(out_h):
        y0 = int(np.floor(oy * src_h / out_h))
        y1 = max(y0 + 1, int(np.ceil((oy + 1) * src_h / out_h)))
        y1 = min(src_h, y1)
        for ox in range(out_w):
            x0 = int(np.floor(ox * src_w / out_w))
            x1 = max(x0 + 1, int(np.ceil((ox + 1) * src_w / out_w)))
            x1 = min(src_w, x1)
            block = source[y0:y1, x0:x1].reshape(-1, 4)
            opaque = block[block[:, 3] >= alpha_threshold]
            if opaque.size == 0:
                continue
            colors, counts = np.unique(opaque[:, :3], axis=0, return_counts=True)
            modal_index = int(np.argmax(counts))
            choice = colors[modal_index]

            if outline == "preserve" and len(colors) > 1:
                luma = 0.2126 * colors[:, 0] + 0.7152 * colors[:, 1] + 0.0722 * colors[:, 2]
                darkest = int(np.argmin(luma))
                share = float(counts[darkest]) / float(counts.sum())
                modal_luma = float(luma[modal_index])
                # A quarter-cell floor prevents a one-pixel speck from turning a
                # whole logical pixel into outline. The 24-level separation is
                # large enough to distinguish a contour from normal tone noise.
                if share >= 0.25 and float(luma[darkest]) <= dark_cutoff and modal_luma - float(luma[darkest]) >= 24.0:
                    choice = colors[darkest]

            result[oy, ox, :3] = choice
            result[oy, ox, 3] = 255
    return Image.fromarray(result, mode="RGBA")


def _dither_settings(mode: DitherMode) -> DitherSettings:
    if mode == "none":
        return DitherSettings(mode="off", strength=0.0, matrix=4)
    if mode == "ordered-low":
        return DitherSettings(mode="ordered", strength=0.18, matrix=4)
    return DitherSettings(mode="ordered", strength=0.35, matrix=4)


def pixelize_image(image: Image.Image, options: PixelizeOptions) -> tuple[Image.Image, tuple[tuple[int, int, int, int], ...], dict[str, Any]]:
    source, warnings = _normalise_alpha(image, options)
    logical_size = _logical_size(source.size, options.target_size)
    palette_size = options.palette_size or _auto_palette_size(source, options.alpha_threshold)
    palette = build_palette([source], palette_size, alpha_threshold=options.alpha_threshold, iterations=6)
    if not palette:
        warnings.append({"code": "empty-source", "message": "no opaque pixels remain after alpha normalization"})
        logical = Image.new("RGBA", logical_size, (0, 0, 0, 0))
    else:
        mapped = apply_palette(source, palette, alpha_threshold=options.alpha_threshold)
        logical = _dominant_downsample(
            mapped,
            palette,
            logical_size,
            outline=options.outline,
            alpha_threshold=options.alpha_threshold,
        )
        if options.dither != "none":
            logical = apply_dither(logical, palette, _dither_settings(options.dither), alpha_threshold=options.alpha_threshold)

    report: dict[str, Any] = {
        "kind": "sprite-studio-pixelize",
        "version": 1,
        "source_size": list(image.size),
        "logical_size": list(logical_size),
        "profile": {
            **asdict(options),
            "palette_mode": "auto" if options.palette_size is None else "fixed",
            "resolved_palette_size": len(palette),
            "color_space": "oklab",
            "downsample_mode": "dominant-cell",
            "alpha_mode": "binary" if options.background == "cleanup" else "thresholded-on-output",
        },
        "palette": {
            "requested": palette_size,
            "colors": len(palette),
            "entries": [list(entry) for entry in palette],
            "separation": palette_distance_report(palette),
        },
        "warnings": warnings,
    }
    return logical, tuple(palette), report


def pixelize_file(
    input_path: Path,
    output_dir: Path,
    options: PixelizeOptions,
    *,
    stem: str = "master_pixel",
) -> PixelizeResult:
    if not input_path.is_file():
        raise FileNotFoundError(f"pixelize source not found: {input_path}")
    output_dir.mkdir(parents=True, exist_ok=True)
    with Image.open(input_path) as opened:
        source = opened.convert("RGBA")
    logical, palette, report = pixelize_image(source, options)

    output_path = output_dir / f"{stem}.png"
    palette_path = output_dir / f"{stem}.palette.json"
    profile_path = output_dir / f"{stem}.pixel-profile.json"
    report_path = output_dir / f"{stem}.pixelize-report.json"
    preview_path = output_dir / f"{stem}.preview-4x.png"

    atomic_save_image(logical, output_path)
    atomic_save_image(
        logical.resize((logical.width * 4, logical.height * 4), Image.Resampling.NEAREST),
        preview_path,
    )
    atomic_write_text(
        palette_path,
        json.dumps({"kind": "sprite-studio-pixel-palette", "entries": [list(entry) for entry in palette]}, ensure_ascii=False, indent=2) + "\n",
    )
    atomic_write_text(
        profile_path,
        json.dumps(report["profile"], ensure_ascii=False, indent=2) + "\n",
    )
    atomic_write_text(report_path, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return PixelizeResult(
        output_path=output_path,
        palette_path=palette_path,
        profile_path=profile_path,
        report_path=report_path,
        preview_path=preview_path,
        logical_size=logical.size,
        palette=palette,
        warnings=tuple(report["warnings"]),
        report=report,
    )
