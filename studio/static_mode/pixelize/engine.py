# SPDX-License-Identifier: Apache-2.0
"""Illustration -> subject-sized logical pixel master conversion.

Pixelize remains a deterministic M1 path, but M1.1 changes the quality order:

    source RGBA
      -> alpha/background normalization
      -> subject detection or explicit crop
      -> subject-height sprite sizing
      -> subject-scoped palette
      -> feature-aware cell sampling
      -> optional dither
      -> thin-feature recovery

The old whole-image and dominant-colour behaviour is kept as a report-compatible
concept, but the actual cell decision now considers area, edges, local contrast,
and dark outline candidates.
"""

from __future__ import annotations

import json
from collections import deque
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from sprite_studio.spec.runio import atomic_save_image, atomic_write_text
from studio.shared.config import DitherSettings
from studio.shared.palette import apply_palette, build_palette, palette_distance_report
from studio.static_mode.refine.dither import apply_dither
from .resolution import SUPPORTED_LOGICAL_HEIGHTS
from .validation import PixelMasterValidationError, validate_deterministic_pixel_master, validate_pixelize_artifacts


SUPPORTED_SIZES = SUPPORTED_LOGICAL_HEIGHTS
SUPPORTED_PALETTES = (16, 24, 32, 48)
DitherMode = Literal["none", "ordered-low", "ordered"]
BackgroundMode = Literal["keep", "cleanup"]
OutlineMode = Literal["preserve", "auto"]
SubjectMode = Literal["auto", "manual"]
DetailMode = Literal["clean", "balanced", "detailed"]
SubjectBox = tuple[int, int, int, int]


@dataclass(frozen=True)
class PixelizeOptions:
    """Stable, serializable Pixelize M1.1 contract.

    ``target_size`` is now the requested character height, not the longest edge
    of the input image. ``subject_bbox`` uses source-image pixel coordinates in
    ``left, top, right, bottom`` order when ``subject_mode`` is ``manual``.
    """

    target_size: int = 128
    palette_size: int | None = 32
    dither: DitherMode = "none"
    background: BackgroundMode = "keep"
    outline: OutlineMode = "preserve"
    alpha_threshold: int = 128
    subject_mode: SubjectMode = "auto"
    subject_bbox: SubjectBox | None = None
    detail: DetailMode = "balanced"

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
        if self.subject_mode not in {"auto", "manual"}:
            raise ValueError("subject_mode must be auto or manual")
        if self.detail not in {"clean", "balanced", "detailed"}:
            raise ValueError("detail must be clean, balanced, or detailed")
        if not (1 <= self.alpha_threshold <= 254):
            raise ValueError("alpha_threshold must be between 1 and 254")
        if self.subject_bbox is not None:
            if len(self.subject_bbox) != 4:
                raise ValueError("subject_bbox must contain left, top, right, bottom")
            left, top, right, bottom = self.subject_bbox
            if right <= left or bottom <= top:
                raise ValueError("subject_bbox must have positive width and height")
        if self.subject_mode == "manual" and self.subject_bbox is None:
            raise ValueError("manual subject mode requires subject_bbox")


@dataclass(frozen=True)
class PixelizeResult:
    output_path: Path
    palette_path: Path
    profile_path: Path
    report_path: Path
    preview_path: Path
    subject_path: Path
    logical_size: tuple[int, int]
    palette: tuple[tuple[int, int, int, int], ...]
    warnings: tuple[dict[str, Any], ...]
    report: dict[str, Any]
    subject_bbox: SubjectBox
    subject_candidates: tuple[dict[str, Any], ...]


def _logical_size(subject_size: tuple[int, int], target_height: int) -> tuple[int, int]:
    width, height = subject_size
    if width <= 0 or height <= 0:
        raise ValueError(f"subject image has invalid size {subject_size}")
    return max(1, int(round(width * target_height / height))), target_height


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
                "message": "background cleanup will use subject detection because the source is fully opaque",
            })
        source[:, :, 3] = np.where(alpha >= options.alpha_threshold, 255, 0).astype(np.uint8)
    elif had_partial_alpha:
        warnings.append({
            "code": "partial-alpha-kept",
            "message": "source contains partial alpha and background=keep preserved it until subject mapping",
        })

    transparent = source[:, :, 3] < options.alpha_threshold
    source[transparent, :3] = 0
    if options.background == "cleanup":
        source[transparent, 3] = 0
    return Image.fromarray(source, mode="RGBA"), warnings


def _bbox(mask: np.ndarray) -> SubjectBox | None:
    ys, xs = np.where(mask)
    if len(xs) == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max() + 1), int(ys.max() + 1)


def _trim_subject_content(
    crop: np.ndarray,
    source_bbox: SubjectBox,
    alpha_threshold: int,
) -> tuple[np.ndarray, SubjectBox]:
    """Remove detector/crop padding so target height describes the subject."""
    local_bbox = _bbox(crop[:, :, 3] >= alpha_threshold)
    if local_bbox is None:
        return crop, source_bbox
    left, top, right, bottom = local_bbox
    source_left, source_top, _, _ = source_bbox
    content_bbox = (
        source_left + left,
        source_top + top,
        source_left + right,
        source_top + bottom,
    )
    return crop[top:bottom, left:right].copy(), content_bbox


def _border_connected_chroma_background(
    source: np.ndarray,
    reference_rgb: np.ndarray,
    alpha_threshold: int,
) -> np.ndarray:
    """Find chroma-key-like pixels connected to the image border.

    RGB distance alone leaves antialiased green-screen spill and noisy key-colour
    pixels inside the subject crop. For saturated border colours, flood through
    a broad chroma band from the image border, remove near-identical key chroma
    globally, and remove a one-pixel halo of lighter mixed key colour adjacent
    to that exterior region. Enclosed, less key-like green details remain
    foreground. Exact background-hue details are inherently indistinguishable
    from chroma-key contamination and are treated as key.
    """
    reference = np.asarray(reference_rgb, dtype=np.float32) / 255.0
    reference_max = float(reference.max(initial=0.0))
    if reference_max <= 0.0 or float(reference.max() - reference.min()) < 64.0 / 255.0:
        return np.zeros(source.shape[:2], dtype=bool)

    reference_chroma = reference / reference_max
    rgb = source[:, :, :3].astype(np.float32) / 255.0
    maximum = np.max(rgb, axis=2, keepdims=True)
    chroma = np.divide(rgb, maximum, out=np.zeros_like(rgb), where=maximum > 1e-6)
    chroma_distance = np.sqrt(np.sum((chroma - reference_chroma) ** 2, axis=2))
    candidate = (chroma_distance <= 0.62) & (source[:, :, 3] >= alpha_threshold)
    if not candidate.any():
        return np.zeros(source.shape[:2], dtype=bool)
    # ``fromarray`` may expose a read-only view; Pillow's floodfill silently
    # leaves such images unchanged, so copy before mutating the mask.
    flood = Image.fromarray((candidate.astype(np.uint8) * 255), mode="L").copy()
    height, width = candidate.shape
    border_points = (
        [(x, 0) for x in range(width)]
        + [(x, height - 1) for x in range(width)]
        + [(0, y) for y in range(1, height - 1)]
        + [(width - 1, y) for y in range(1, height - 1)]
    )
    for point in border_points:
        if flood.getpixel(point) == 255:
            ImageDraw.floodfill(flood, point, 0, thresh=0)

    filled = np.asarray(flood, dtype=np.uint8)
    border_connected = candidate & (filled == 0)
    exact_hue_key = (chroma_distance <= 0.15) & (source[:, :, 3] >= alpha_threshold)
    near_border = np.asarray(
        Image.fromarray((border_connected.astype(np.uint8) * 255), mode="L").filter(ImageFilter.MaxFilter(3)),
        dtype=np.uint8,
    ) > 0
    blended_edge_spill = (
        (chroma_distance <= 0.80)
        & (source[:, :, 3] >= alpha_threshold)
        & near_border
    )
    return exact_hue_key | border_connected | blended_edge_spill


def _border_foreground_mask(source: np.ndarray, alpha_threshold: int) -> np.ndarray:
    """Find foreground away from the dominant border colour and its spill."""
    height, width, _ = source.shape
    border = np.concatenate((source[0, :, :], source[-1, :, :], source[:, 0, :], source[:, -1, :]), axis=0)
    valid_border = border[border[:, 3] >= alpha_threshold]
    if valid_border.size == 0:
        return source[:, :, 3] >= alpha_threshold
    quantised = (valid_border[:, :3] // 16).astype(np.uint8)
    colours, counts = np.unique(quantised, axis=0, return_counts=True)
    reference = colours[int(np.argmax(counts))].astype(np.float32) * 16.0 + 8.0
    distance = np.sqrt(np.sum((source[:, :, :3].astype(np.float32) - reference) ** 2, axis=2))
    opaque = source[:, :, 3] >= alpha_threshold
    connected_chroma = _border_connected_chroma_background(source, reference, alpha_threshold)
    mask = (distance >= 28.0) & opaque & ~connected_chroma
    minimum = max(8, int(height * width * 0.001))
    if int(mask.sum()) < minimum:
        mask = (distance >= 16.0) & opaque & ~connected_chroma

    # A few antialiased screen-colour pixels can be separated from the exterior
    # by hair/outline pixels and therefore evade border-connected flood fill.
    # Only trim bright, strongly green pixels in the one-pixel silhouette edge;
    # interior green costume, eyes, and accessories remain untouched.
    reference_rgb = reference / 255.0
    reference_max = float(reference_rgb.max(initial=0.0))
    if reference_max > 0.0 and float(reference_rgb.max() - reference_rgb.min()) >= 64.0 / 255.0:
        reference_chroma = reference_rgb / reference_max
        rgb = source[:, :, :3].astype(np.float32) / 255.0
        rgb_max = np.max(rgb, axis=2, keepdims=True)
        chroma = np.divide(rgb, rgb_max, out=np.zeros_like(rgb), where=rgb_max > 1e-6)
        chroma_distance = np.sqrt(np.sum((chroma - reference_chroma) ** 2, axis=2))
        eroded = np.asarray(
            Image.fromarray((mask.astype(np.uint8) * 255), mode="L").filter(ImageFilter.MinFilter(3)),
            dtype=np.uint8,
        ) > 0
        green = source[:, :, 1].astype(np.int16)
        other_channels = np.maximum(source[:, :, 0], source[:, :, 2]).astype(np.int16)
        likely_edge_spill = (
            mask
            & ~eroded
            & opaque
            & (chroma_distance <= 0.80)
            & (green >= 150)
            & (green - other_channels >= 70)
        )
        mask &= ~likely_edge_spill
    return mask


def _component_candidates(mask: np.ndarray, *, max_candidates: int = 8) -> list[dict[str, Any]]:
    """Return deterministic connected-component candidates on a bounded grid."""
    height, width = mask.shape
    scale = min(1.0, 256.0 / max(height, width))
    small_w = max(1, int(round(width * scale)))
    small_h = max(1, int(round(height * scale)))
    small = np.asarray(
        Image.fromarray((mask.astype(np.uint8) * 255), mode="L").resize((small_w, small_h), Image.Resampling.NEAREST),
        dtype=np.uint8,
    ) > 0
    visited = np.zeros_like(small, dtype=bool)
    candidates: list[dict[str, Any]] = []
    for sy in range(small_h):
        for sx in range(small_w):
            if not small[sy, sx] or visited[sy, sx]:
                continue
            queue: deque[tuple[int, int]] = deque([(sx, sy)])
            visited[sy, sx] = True
            area = 0
            left = right = sx
            top = bottom = sy
            while queue:
                x, y = queue.popleft()
                area += 1
                left, right = min(left, x), max(right, x)
                top, bottom = min(top, y), max(bottom, y)
                for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1), (x - 1, y - 1), (x + 1, y + 1), (x - 1, y + 1), (x + 1, y - 1)):
                    if 0 <= nx < small_w and 0 <= ny < small_h and small[ny, nx] and not visited[ny, nx]:
                        visited[ny, nx] = True
                        queue.append((nx, ny))
            if area < max(4, int(small_w * small_h * 0.001)):
                continue
            box_width = max(1, int(round((right + 1) / scale)) - int(np.floor(left / scale)))
            box_height = max(1, int(round((bottom + 1) / scale)) - int(np.floor(top / scale)))
            x0 = max(0, int(np.floor(left / scale)))
            y0 = max(0, int(np.floor(top / scale)))
            x1 = min(width, x0 + box_width)
            y1 = min(height, y0 + box_height)
            padding = max(2, int(round(max(x1 - x0, y1 - y0) * 0.04)))
            x0, y0 = max(0, x0 - padding), max(0, y0 - padding)
            x1, y1 = min(width, x1 + padding), min(height, y1 + padding)
            candidates.append({"bbox": [x0, y0, x1, y1], "area": int(area), "confidence": round(float(area / max(1, small_w * small_h)), 6)})
    candidates.sort(key=lambda item: (-int(item["area"]), item["bbox"]))
    return candidates[:max_candidates]


def _subject_selection(source: Image.Image, options: PixelizeOptions) -> tuple[Image.Image, SubjectBox, list[dict[str, Any]], list[dict[str, Any]]]:
    array = np.asarray(source.convert("RGBA"), dtype=np.uint8)
    height, width, _ = array.shape
    warnings: list[dict[str, Any]] = []
    has_transparency = bool(np.any(array[:, :, 3] < 255))
    alpha_mask = array[:, :, 3] >= options.alpha_threshold
    foreground = alpha_mask if has_transparency else _border_foreground_mask(array, options.alpha_threshold)

    if options.subject_mode == "manual":
        assert options.subject_bbox is not None
        left, top, right, bottom = options.subject_bbox
        left, top = max(0, int(left)), max(0, int(top))
        right, bottom = min(width, int(right)), min(height, int(bottom))
        selected = (left, top, right, bottom)
        if right <= left or bottom <= top:
            raise ValueError(f"subject_bbox {options.subject_bbox} is outside the source image")
        candidates = [{"bbox": list(selected), "area": int(foreground[top:bottom, left:right].sum()), "confidence": 1.0, "mode": "manual"}]
        crop = array[top:bottom, left:right].copy()
        if options.background == "cleanup" and not has_transparency:
            local_mask = _border_foreground_mask(crop, options.alpha_threshold)
            crop[:, :, 3] = np.where(local_mask, 255, 0).astype(np.uint8)
            crop[~local_mask, :3] = 0
        crop, content_bbox = _trim_subject_content(crop, selected, options.alpha_threshold)
        return Image.fromarray(crop, mode="RGBA"), content_bbox, candidates, warnings

    candidates = _component_candidates(foreground)
    full_box = _bbox(foreground)
    if full_box is None:
        warnings.append({"code": "subject-not-detected", "message": "no subject pixels were detected; using the full source image"})
        full_box = (0, 0, width, height)
        foreground = alpha_mask
    if has_transparency:
        # Transparent character art commonly has disconnected limbs, hair, and
        # accessories. The alpha bbox keeps the entire character together.
        selected = full_box
        candidates = [{"bbox": list(selected), "area": int(foreground.sum()), "confidence": 1.0, "mode": "alpha-bbox"}]
    else:
        selected = tuple(int(value) for value in candidates[0]["bbox"]) if candidates else full_box
        if len(candidates) > 1:
            warnings.append({"code": "multiple-subject-candidates", "message": "auto detect selected the largest candidate; use manual crop to choose another subject", "candidates": candidates})
    left, top, right, bottom = selected
    crop = array[top:bottom, left:right].copy()
    local_mask = foreground[top:bottom, left:right]
    if not has_transparency:
        crop[:, :, 3] = np.where(local_mask, 255, 0).astype(np.uint8)
        crop[~local_mask, :3] = 0
        warnings.append({"code": "opaque-background-masked", "message": "auto subject detection masked background pixels outside the selected subject"})
    crop, content_bbox = _trim_subject_content(crop, selected, options.alpha_threshold)
    return Image.fromarray(crop, mode="RGBA"), content_bbox, candidates, warnings


def _auto_palette_size(image: Image.Image, alpha_threshold: int, detail: DetailMode) -> int:
    array = np.asarray(image.convert("RGBA"), dtype=np.uint8).reshape(-1, 4)
    opaque = array[array[:, 3] >= alpha_threshold]
    if opaque.size == 0:
        return 16
    unique = int(np.unique(opaque[:, :3], axis=0).shape[0])
    base = 16 if unique <= 32 else 24 if unique <= 128 else 32 if unique <= 768 else 48
    if detail == "clean":
        return min(24, max(16, base))
    if detail == "detailed":
        return min(48, max(32, base))
    return base


def _feature_maps(image: Image.Image, alpha_threshold: int) -> tuple[np.ndarray, np.ndarray]:
    source = np.asarray(image.convert("RGBA"), dtype=np.uint8)
    rgb = source[:, :, :3].astype(np.float32)
    luma = 0.2126 * rgb[:, :, 0] + 0.7152 * rgb[:, :, 1] + 0.0722 * rgb[:, :, 2]
    left = np.roll(luma, 1, axis=1)
    right = np.roll(luma, -1, axis=1)
    up = np.roll(luma, 1, axis=0)
    down = np.roll(luma, -1, axis=0)
    left[:, 0], right[:, -1], up[0, :], down[-1, :] = luma[:, 0], luma[:, -1], luma[0, :], luma[-1, :]
    edge = (np.abs(luma - left) + np.abs(luma - right) + np.abs(luma - up) + np.abs(luma - down)) / 4.0
    contrast = np.maximum.reduce((np.abs(luma - left), np.abs(luma - right), np.abs(luma - up), np.abs(luma - down)))
    opaque = source[:, :, 3] >= alpha_threshold
    edge[~opaque] = 0.0
    contrast[~opaque] = 0.0
    return edge, contrast


def _cell_bounds(index: int, source_length: int, output_length: int) -> tuple[int, int]:
    start = int(np.floor(index * source_length / output_length))
    end = min(source_length, max(start + 1, int(np.ceil((index + 1) * source_length / output_length))))
    return start, end


def _feature_aware_downsample(
    mapped: Image.Image,
    palette: tuple[tuple[int, int, int, int], ...],
    size: tuple[int, int],
    *,
    outline: OutlineMode,
    detail: DetailMode,
    alpha_threshold: int,
) -> tuple[Image.Image, dict[str, int]]:
    """Pick one palette colour per cell using area + edge + contrast scores."""
    source = np.asarray(mapped.convert("RGBA"), dtype=np.uint8)
    src_h, src_w, _ = source.shape
    out_w, out_h = size
    result = np.zeros((out_h, out_w, 4), dtype=np.uint8)
    edge_map, contrast_map = _feature_maps(mapped, alpha_threshold)
    palette_rgb = np.asarray([entry[:3] for entry in palette], dtype=np.float64) if palette else np.zeros((0, 3))
    palette_luma = 0.2126 * palette_rgb[:, 0] + 0.7152 * palette_rgb[:, 1] + 0.0722 * palette_rgb[:, 2]
    dark_cutoff = float(np.quantile(palette_luma, 0.30)) if len(palette_luma) else 0.0
    weights = {"clean": (0.72, 0.18, 0.10), "balanced": (0.56, 0.26, 0.18), "detailed": (0.45, 0.32, 0.23)}[detail]
    stats = {"feature_cells": 0, "outline_cells": 0}

    for oy in range(out_h):
        y0, y1 = _cell_bounds(oy, src_h, out_h)
        for ox in range(out_w):
            x0, x1 = _cell_bounds(ox, src_w, out_w)
            block = source[y0:y1, x0:x1].reshape(-1, 4)
            opaque_mask = block[:, 3] >= alpha_threshold
            if not opaque_mask.any():
                continue
            opaque = block[opaque_mask]
            colours, counts = np.unique(opaque[:, :3], axis=0, return_counts=True)
            area_score = counts.astype(np.float64) / max(1, counts.sum())
            edge_values = edge_map[y0:y1, x0:x1].reshape(-1)[opaque_mask]
            contrast_values = contrast_map[y0:y1, x0:x1].reshape(-1)[opaque_mask]
            edge_score = np.zeros(len(colours), dtype=np.float64)
            contrast_score = np.zeros(len(colours), dtype=np.float64)
            for index, colour in enumerate(colours):
                matching = np.all(opaque[:, :3] == colour, axis=1)
                edge_score[index] = float(edge_values[matching].sum())
                contrast_score[index] = float(contrast_values[matching].sum())
            if edge_score.sum() > 0:
                edge_score /= edge_score.sum()
            if contrast_score.sum() > 0:
                contrast_score /= contrast_score.sum()
            scores = weights[0] * area_score + weights[1] * edge_score + weights[2] * contrast_score
            luma = 0.2126 * colours[:, 0] + 0.7152 * colours[:, 1] + 0.0722 * colours[:, 2]
            dark_candidates = np.where((luma <= dark_cutoff) & (edge_score >= 0.08) & (contrast_score >= 0.04) & (area_score >= 0.04))[0]
            if outline in {"preserve", "auto"} and len(dark_candidates):
                scores[dark_candidates] += 0.12 if detail == "clean" else 0.18
                stats["outline_cells"] += 1
            choice_index = int(np.argmax(scores))
            result[oy, ox, :3] = colours[choice_index]
            result[oy, ox, 3] = 255
            if edge_score[choice_index] >= 0.08 or contrast_score[choice_index] >= 0.08:
                stats["feature_cells"] += 1
    return Image.fromarray(result, mode="RGBA"), stats


def _thin_feature_recovery(
    logical: Image.Image,
    mapped: Image.Image,
    palette: tuple[tuple[int, int, int, int], ...],
    *,
    outline: OutlineMode,
    detail: DetailMode,
    alpha_threshold: int,
) -> tuple[Image.Image, int]:
    """Restore strong dark one/two-pixel features without reintroducing noise."""
    if outline not in {"preserve", "auto"} or not palette:
        return logical, 0
    result = np.asarray(logical.convert("RGBA"), dtype=np.uint8).copy()
    source = np.asarray(mapped.convert("RGBA"), dtype=np.uint8)
    edge_map, contrast_map = _feature_maps(mapped, alpha_threshold)
    palette_rgb = np.asarray([entry[:3] for entry in palette], dtype=np.float64)
    palette_luma = 0.2126 * palette_rgb[:, 0] + 0.7152 * palette_rgb[:, 1] + 0.0722 * palette_rgb[:, 2]
    dark_cutoff = float(np.quantile(palette_luma, 0.30))
    recovered = 0
    out_h, out_w, _ = result.shape
    src_h, src_w, _ = source.shape

    for oy in range(out_h):
        y0, y1 = _cell_bounds(oy, src_h, out_h)
        for ox in range(out_w):
            x0, x1 = _cell_bounds(ox, src_w, out_w)
            block = source[y0:y1, x0:x1].reshape(-1, 4)
            opaque_mask = block[:, 3] >= alpha_threshold
            if not opaque_mask.any():
                continue
            colours, counts = np.unique(block[opaque_mask, :3], axis=0, return_counts=True)
            luma = 0.2126 * colours[:, 0] + 0.7152 * colours[:, 1] + 0.0722 * colours[:, 2]
            dark = np.where(luma <= dark_cutoff)[0]
            if not len(dark):
                continue
            edge_values = edge_map[y0:y1, x0:x1].reshape(-1)[opaque_mask]
            contrast_values = contrast_map[y0:y1, x0:x1].reshape(-1)[opaque_mask]
            total_edge = float(edge_values.sum())
            total_contrast = float(contrast_values.sum())
            candidate = None
            for index in dark[np.argsort(-counts[dark])]:
                matching = np.all(block[opaque_mask, :3] == colours[index], axis=1)
                edge_share = float(edge_values[matching].sum()) / max(total_edge, 1.0)
                contrast_share = float(contrast_values[matching].sum()) / max(total_contrast, 1.0)
                if edge_share >= 0.10 and contrast_share >= 0.06 and float(contrast_values[matching].max(initial=0.0)) >= 18.0:
                    candidate = colours[index]
                    break
            if candidate is None:
                continue
            current = result[oy, ox, :3]
            if np.array_equal(current, candidate):
                continue
            neighbours = 0
            for ny in range(max(0, oy - 1), min(out_h, oy + 2)):
                for nx in range(max(0, ox - 1), min(out_w, ox + 2)):
                    if (ny != oy or nx != ox) and result[ny, nx, 3] >= 255:
                        neighbours += 1
            if neighbours >= 2 or detail == "detailed":
                result[oy, ox, :3] = candidate
                result[oy, ox, 3] = 255
                recovered += 1
    return Image.fromarray(result, mode="RGBA"), recovered


def _dither_settings(mode: DitherMode) -> DitherSettings:
    if mode == "none":
        return DitherSettings(mode="off", strength=0.0, matrix=4)
    if mode == "ordered-low":
        return DitherSettings(mode="ordered", strength=0.18, matrix=4)
    return DitherSettings(mode="ordered", strength=0.35, matrix=4)


def pixelize_image(image: Image.Image, options: PixelizeOptions) -> tuple[Image.Image, tuple[tuple[int, int, int, int], ...], dict[str, Any]]:
    source, warnings = _normalise_alpha(image, options)
    subject, subject_bbox, candidates, subject_warnings = _subject_selection(source, options)
    warnings.extend(subject_warnings)
    logical_size = _logical_size(subject.size, options.target_size)
    palette_size = options.palette_size or _auto_palette_size(subject, options.alpha_threshold, options.detail)
    palette = build_palette([subject], palette_size, alpha_threshold=options.alpha_threshold, iterations=6)
    recovery_count = 0
    scoring_stats = {"feature_cells": 0, "outline_cells": 0}
    if not palette:
        warnings.append({"code": "empty-source", "message": "no opaque pixels remain after subject selection"})
        logical = Image.new("RGBA", logical_size, (0, 0, 0, 0))
    else:
        mapped = apply_palette(subject, palette, alpha_threshold=options.alpha_threshold)
        logical, scoring_stats = _feature_aware_downsample(
            mapped,
            palette,
            logical_size,
            outline=options.outline,
            detail=options.detail,
            alpha_threshold=options.alpha_threshold,
        )
        if options.dither != "none":
            logical = apply_dither(logical, palette, _dither_settings(options.dither), alpha_threshold=options.alpha_threshold)
        logical, recovery_count = _thin_feature_recovery(
            logical,
            mapped,
            palette,
            outline=options.outline,
            detail=options.detail,
            alpha_threshold=options.alpha_threshold,
        )

    report: dict[str, Any] = {
        "kind": "sprite-studio-pixelize",
        "version": 2,
        "source_size": list(image.size),
        "subject_size": list(subject.size),
        "subject_bbox": list(subject_bbox),
        "subject_candidates": candidates,
        "logical_size": list(logical_size),
        "profile": {
            **asdict(options),
            "target_height": options.target_size,
            "subject_bbox": list(subject_bbox),
            "palette_mode": "auto" if options.palette_size is None else "fixed",
            "resolved_palette_size": len(palette),
            "palette_scope": "subject",
            "color_space": "oklab",
            "downsample_mode": "dominant-cell",
            "cell_scoring": "area+edge+contrast+outline",
            "thin_feature_recovery": True,
            "thin_feature_recovered_cells": recovery_count,
            "feature_cells": scoring_stats["feature_cells"],
            "outline_cells": scoring_stats["outline_cells"],
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
    report["validation"] = validate_deterministic_pixel_master(
        logical,
        palette,
        target_height=options.target_size,
        alpha_threshold=options.alpha_threshold,
        max_palette_size=palette_size,
    ).to_dict()
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
    normalized, _ = _normalise_alpha(source, options)
    subject, selected_bbox, candidates, _ = _subject_selection(normalized, options)
    subject_bbox = tuple(int(value) for value in selected_bbox)
    subject_candidates = tuple(candidates)

    output_path = output_dir / f"{stem}.png"
    palette_path = output_dir / f"{stem}.palette.json"
    profile_path = output_dir / f"{stem}.pixel-profile.json"
    report_path = output_dir / f"{stem}.pixelize-report.json"
    preview_path = output_dir / f"{stem}.preview-4x.png"
    subject_path = output_dir / f"{stem}.subject.png"

    preview = logical.resize((logical.width * 4, logical.height * 4), Image.Resampling.NEAREST)
    atomic_save_image(logical, output_path)
    atomic_save_image(preview, preview_path)
    atomic_save_image(subject, subject_path)
    atomic_write_text(
        palette_path,
        json.dumps({"kind": "sprite-studio-pixel-palette", "entries": [list(entry) for entry in palette]}, ensure_ascii=False, indent=2) + "\n",
    )
    validation = validate_pixelize_artifacts(
        logical,
        palette,
        target_height=options.target_size,
        alpha_threshold=options.alpha_threshold,
        max_palette_size=int(report["palette"]["requested"]),
        output_path=output_path,
        preview_path=preview_path,
        subject_path=subject_path,
    )
    report["validation"] = validation.to_dict()
    atomic_write_text(profile_path, json.dumps(report["profile"], ensure_ascii=False, indent=2) + "\n")
    atomic_write_text(report_path, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    if not validation.pass_:
        raise PixelMasterValidationError(validation)
    return PixelizeResult(
        output_path=output_path,
        palette_path=palette_path,
        profile_path=profile_path,
        report_path=report_path,
        preview_path=preview_path,
        subject_path=subject_path,
        logical_size=logical.size,
        palette=palette,
        warnings=tuple(report["warnings"]),
        report=report,
        subject_bbox=subject_bbox,
        subject_candidates=subject_candidates,
    )
