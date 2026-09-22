# SPDX-License-Identifier: Apache-2.0
"""Gentle cleanup for AI-authored Pixel Master candidates.

The deterministic Pixelize engine intentionally makes a hard per-cell choice.
That is useful for Preserve, but it damages already-authored AI pixel clusters.
This module therefore does only bounded operations: remove a detectable border
or chroma background, crop the surviving subject, scale with nearest-neighbour,
optionally apply a palette lock, harden alpha, and remove truly isolated noise.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any

import numpy as np
from PIL import Image

from studio.shared.palette import apply_palette, build_palette, palette_distance_report

from .resolution import AUTO_LOGICAL_HEIGHTS


@dataclass(frozen=True)
class AiPixelMasterCleanupOptions:
    target_size: int = 128
    palette_size: int | None = None
    alpha_threshold: int = 128
    background_tolerance: float = 28.0
    remove_isolated_area: int = 1
    geometry_resize: bool = True
    remove_background: bool = True

    def __post_init__(self) -> None:
        if self.target_size not in {64, 96, *AUTO_LOGICAL_HEIGHTS}:
            raise ValueError("target_size must be one of 64, 96, 128, 160, 192, or 256")
        if self.palette_size is not None and self.palette_size not in {16, 24, 32, 48}:
            raise ValueError("palette_size must be auto/None or one of 16, 24, 32, 48")
        if not 1 <= self.alpha_threshold <= 254:
            raise ValueError("alpha_threshold must be between 1 and 254")
        if self.background_tolerance <= 0:
            raise ValueError("background_tolerance must be positive")
        if self.remove_isolated_area < 0:
            raise ValueError("remove_isolated_area must be non-negative")


@dataclass(frozen=True)
class AiPixelMasterCleanupResult:
    image: Image.Image
    subject_bbox: tuple[int, int, int, int]
    palette: tuple[tuple[int, int, int, int], ...]
    report: dict[str, Any]
    warnings: tuple[dict[str, Any], ...]


def _chroma_masks(rgb: np.ndarray) -> dict[str, np.ndarray]:
    red, green, blue = (rgb[:, :, index].astype(np.int16) for index in range(3))
    return {
        "magenta": (red >= 170) & (blue >= 170) & (green <= 115) & ((red - green) >= 70) & ((blue - green) >= 70),
        "green": (green >= 170) & (red <= 115) & (blue <= 115) & ((green - red) >= 70) & ((green - blue) >= 70),
    }


def _border_reference(rgb: np.ndarray) -> np.ndarray:
    border = np.concatenate((rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]), axis=0)
    quantised = (border // 16).astype(np.uint8)
    colours, counts = np.unique(quantised, axis=0, return_counts=True)
    return colours[int(np.argmax(counts))].astype(np.float32) * 16.0 + 8.0


def _border_connected(mask: np.ndarray) -> np.ndarray:
    height, width = mask.shape
    visited = np.zeros_like(mask, dtype=bool)
    queue: deque[tuple[int, int]] = deque()
    for x in range(width):
        if mask[0, x]:
            visited[0, x] = True
            queue.append((x, 0))
        if mask[height - 1, x] and not visited[height - 1, x]:
            visited[height - 1, x] = True
            queue.append((x, height - 1))
    for y in range(height):
        if mask[y, 0] and not visited[y, 0]:
            visited[y, 0] = True
            queue.append((0, y))
        if mask[y, width - 1] and not visited[y, width - 1]:
            visited[y, width - 1] = True
            queue.append((width - 1, y))
    while queue:
        x, y = queue.popleft()
        for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if 0 <= nx < width and 0 <= ny < height and mask[ny, nx] and not visited[ny, nx]:
                visited[ny, nx] = True
                queue.append((nx, ny))
    return visited


def _background_mask(array: np.ndarray, tolerance: float) -> tuple[np.ndarray, str, dict[str, int]]:
    rgb = array[:, :, :3]
    alpha = array[:, :, 3]
    opaque = alpha > 0
    total = max(1, rgb.shape[0] * rgb.shape[1])
    chroma = _chroma_masks(rgb)
    for key, mask in chroma.items():
        count = int(np.count_nonzero(mask & opaque))
        if count >= max(16, int(total * 0.005)):
            connected = _border_connected(mask & opaque)
            connected_count = int(np.count_nonzero(connected))
            # A PSE logical crop can be fully opaque and touch every canvas
            # edge.  In that case a uniform subject is not evidence of a
            # removable background; deleting the border-connected pixels
            # would delete the entire accepted sprite.
            if connected_count == int(np.count_nonzero(opaque)) == total:
                continue
            if connected_count:
                return connected, f"chroma:{key}", {
                    "keyed_pixels": count,
                    "background_pixels": connected_count,
                }

    reference = _border_reference(rgb)
    distance = np.sqrt(np.sum((rgb.astype(np.float32) - reference) ** 2, axis=2))
    candidate = (distance <= tolerance) & opaque
    if np.count_nonzero(candidate) < max(16, int(total * 0.05)):
        return np.zeros_like(opaque), "none", {"keyed_pixels": 0}
    connected = _border_connected(candidate)
    if int(np.count_nonzero(connected)) == int(np.count_nonzero(opaque)) == total:
        return np.zeros_like(opaque), "none", {"keyed_pixels": 0}
    return connected, "border-flood", {"background_pixels": int(np.count_nonzero(connected))}


def _subject_bbox(alpha: np.ndarray) -> tuple[int, int, int, int] | None:
    ys, xs = np.where(alpha > 0)
    if not len(xs):
        return None
    return int(xs.min()), int(ys.min()), int(xs.max() + 1), int(ys.max() + 1)


def _painterly_risk(array: np.ndarray) -> tuple[bool, int, float]:
    """Flag unusually color-rich candidates without altering their pixels."""

    opaque = array[:, :, 3] >= 128
    if not opaque.any():
        return False, 0, 0.0
    colours = np.unique(array[:, :, :3][opaque], axis=0)
    area = max(1, int(np.count_nonzero(opaque)))
    colour_count = int(len(colours))
    colour_ratio = colour_count / area
    risk = colour_count >= 256 or (colour_count >= 96 and colour_ratio >= 0.05)
    return risk, colour_count, colour_ratio


def _remove_isolated(image: Image.Image, max_area: int) -> tuple[Image.Image, dict[str, int]]:
    if max_area <= 0:
        return image, {"removed_components": 0, "removed_pixels": 0}
    array = np.asarray(image.convert("RGBA"), dtype=np.uint8).copy()
    mask = array[:, :, 3] == 255
    height, width = mask.shape
    removed_components = 0
    removed_pixels = 0
    visited = np.zeros_like(mask, dtype=bool)
    for y in range(height):
        for x in range(width):
            if not mask[y, x] or visited[y, x]:
                continue
            queue: deque[tuple[int, int]] = deque([(x, y)])
            visited[y, x] = True
            component: list[tuple[int, int]] = []
            while queue:
                cx, cy = queue.popleft()
                component.append((cx, cy))
                for nx, ny in ((cx - 1, cy), (cx + 1, cy), (cx, cy - 1), (cx, cy + 1)):
                    if 0 <= nx < width and 0 <= ny < height and mask[ny, nx] and not visited[ny, nx]:
                        visited[ny, nx] = True
                        queue.append((nx, ny))
            if len(component) > max_area:
                continue
            component_set = set(component)
            has_neighbour = any(
                (nx, ny) in mask_coords
                for cx, cy in component
                for nx in range(max(0, cx - 1), min(width, cx + 2))
                for ny in range(max(0, cy - 1), min(height, cy + 2))
                if (nx, ny) != (cx, cy)
                for mask_coords in (component_set,)
            )
            if has_neighbour:
                continue
            for cx, cy in component:
                array[cy, cx] = (0, 0, 0, 0)
            removed_components += 1
            removed_pixels += len(component)
    return Image.fromarray(array, mode="RGBA"), {"removed_components": removed_components, "removed_pixels": removed_pixels}


def ai_pixel_master_cleanup(image: Image.Image, options: AiPixelMasterCleanupOptions) -> AiPixelMasterCleanupResult:
    """Apply non-destructive-by-default cleanup to an AI Pixel Master candidate."""

    source = np.asarray(image.convert("RGBA"), dtype=np.uint8).copy()
    warnings: list[dict[str, Any]] = []
    painterly_risk, opaque_colors, color_ratio = _painterly_risk(source)
    if painterly_risk:
        warnings.append({"code": "ai-painterly-risk", "message": "Candidate is unusually color-rich for authored pixel clusters; review raw/post before accepting cleanup."})
    if options.remove_background:
        background, background_mode, background_stats = _background_mask(source, options.background_tolerance)
    else:
        background = np.zeros(source.shape[:2], dtype=bool)
        background_mode = "disabled"
        background_stats = {"background_pixels": 0}
    if background.any():
        source[background, 3] = 0
        source[background, :3] = 0
    else:
        warnings.append({"code": "ai-background-not-detected", "message": "AI cleanup could not prove a removable border/chroma background; it was preserved."})

    source[source[:, :, 3] < options.alpha_threshold] = (0, 0, 0, 0)
    precleaned, pre_isolated_report = _remove_isolated(Image.fromarray(source, mode="RGBA"), options.remove_isolated_area)
    source = np.asarray(precleaned.convert("RGBA"), dtype=np.uint8).copy()
    bbox = _subject_bbox(source[:, :, 3])
    if bbox is None:
        warnings.append({"code": "ai-subject-not-detected", "message": "AI cleanup found no opaque subject; preserving the full candidate."})
        cropped = Image.fromarray(source, mode="RGBA")
        bbox = (0, 0, cropped.width, cropped.height)
    else:
        left, top, right, bottom = bbox
        cropped = Image.fromarray(source[top:bottom, left:right], mode="RGBA")

    if not options.geometry_resize:
        # The logical-grid validator already owns geometry and canonical
        # height. Cleanup may remove background/noise and lock a palette, but
        # it must not crop, resample, or otherwise reinterpret the sprite.
        cropped = Image.fromarray(source, mode="RGBA")
        target_width = cropped.width
    else:
        target_width = max(1, int(round(cropped.width * options.target_size / max(1, cropped.height))))
        if cropped.size != (target_width, options.target_size):
            cropped = cropped.resize((target_width, options.target_size), Image.Resampling.NEAREST)

    if options.palette_size is None:
        palette = tuple(
            tuple(int(value) for value in entry)
            for entry in np.unique(np.asarray(cropped.convert("RGBA")).reshape(-1, 4), axis=0)
            if int(entry[3]) >= options.alpha_threshold
        )
        palette_mode = "preserved"
    else:
        palette = build_palette([cropped], options.palette_size, alpha_threshold=options.alpha_threshold, iterations=4)
        cropped = apply_palette(cropped, palette, alpha_threshold=options.alpha_threshold)
        palette_mode = "locked"

    array = np.asarray(cropped.convert("RGBA"), dtype=np.uint8).copy()
    keep = array[:, :, 3] >= options.alpha_threshold
    array[~keep] = (0, 0, 0, 0)
    array[keep, 3] = 255
    cleaned, isolated_report = _remove_isolated(Image.fromarray(array, mode="RGBA"), options.remove_isolated_area)
    final = np.asarray(cleaned.convert("RGBA"), dtype=np.uint8).copy()
    final[final[:, :, 3] == 0, :3] = 0
    result = Image.fromarray(final, mode="RGBA")
    report = {
        "kind": "ai-pixel-master-cleanup",
        "version": 1,
        "input_size": list(image.size),
        "output_size": list(result.size),
        "background": {"mode": background_mode, **background_stats},
        "style_risk": {"painterly": painterly_risk, "opaque_colors": opaque_colors, "color_ratio": color_ratio},
        "subject_bbox": list(bbox),
        "scale": {
            "resampling": "nearest" if options.geometry_resize else None,
            "target_height": options.target_size if options.geometry_resize else None,
        },
        "geometry": {
            "resize": options.geometry_resize,
            "input_size_preserved": not options.geometry_resize,
        },
        "background_policy": {
            "remove_background": options.remove_background,
        },
        "palette": {
            "mode": palette_mode,
            "requested": options.palette_size,
            "colors": len(palette),
            "separation": palette_distance_report(palette) if palette else {},
        },
        "alpha": {"mode": "binary", "threshold": options.alpha_threshold},
        "isolated_noise": {
            "removed_components": pre_isolated_report["removed_components"] + isolated_report["removed_components"],
            "removed_pixels": pre_isolated_report["removed_pixels"] + isolated_report["removed_pixels"],
            "pre_crop": pre_isolated_report,
            "post_scale": isolated_report,
        },
        "outline": {"mode": "preserve", "thickening": False},
        "warnings": warnings,
    }
    return AiPixelMasterCleanupResult(result, bbox, palette, report, tuple(warnings))


__all__ = ["AiPixelMasterCleanupOptions", "AiPixelMasterCleanupResult", "ai_pixel_master_cleanup"]
