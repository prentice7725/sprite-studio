# SPDX-License-Identifier: Apache-2.0
"""Semantic Pixel Structure Extractor (PSE) v0.1.

PSE turns an already simplified semantic pixel-art image into a logical
sprite. It is intentionally different from the strict C1/C2 transport gate:
the input may be a large AI image, but every output logical cell is projected
from its own high-resolution footprint with palette-cluster mode selection.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any

import numpy as np
from PIL import Image

from .resolution import AUTO_LOGICAL_HEIGHTS, require_logical_height


PSE_VERSION = "v0.1"
DEFAULT_PALETTE_SIZE = 48

_RGB_TO_LMS = np.array(
    [
        [0.4122214708, 0.5363325363, 0.0514459929],
        [0.2119034982, 0.6806995451, 0.1073969566],
        [0.0883024619, 0.2817188376, 0.6299787005],
    ],
    dtype=np.float32,
)
_LMS_TO_LAB = np.array(
    [
        [0.2104542553, 0.7936177850, -0.0040720468],
        [1.9779984951, -2.4285922050, 0.4505937099],
        [0.0259040371, 0.7827717662, -0.8086757660],
    ],
    dtype=np.float32,
)


@dataclass(frozen=True)
class StructureExtractorOptions:
    target_height: int = 128
    palette_size: int | None = DEFAULT_PALETTE_SIZE
    alpha_threshold: int = 128
    opaque_coverage_threshold: float = 0.18
    background_tolerance: float = 28.0
    palette_iterations: int = 5
    resize_rescue: bool = False
    palette_relaxation: bool = False
    background_redetect_after_projection: bool = False
    remove_isolated_pixels: bool = False

    def __post_init__(self) -> None:
        require_logical_height(self.target_height)
        if self.palette_size is not None and self.palette_size not in {24, 32, 48}:
            raise ValueError("palette_size must be auto/None or one of 24, 32, 48")
        if not 1 <= self.alpha_threshold <= 254:
            raise ValueError("alpha_threshold must be between 1 and 254")
        if not 0.0 < self.opaque_coverage_threshold <= 1.0:
            raise ValueError("opaque_coverage_threshold must be in (0, 1]")
        if self.background_tolerance <= 0:
            raise ValueError("background_tolerance must be positive")
        if self.palette_iterations < 1:
            raise ValueError("palette_iterations must be positive")


@dataclass(frozen=True)
class StructureExtractionResult:
    image: Image.Image | None
    input_subject_bbox: tuple[int, int, int, int] | None
    palette: tuple[tuple[int, int, int, int], ...]
    report: dict[str, Any]
    warnings: tuple[dict[str, Any], ...]

    @property
    def passed(self) -> bool:
        return self.image is not None


@dataclass(frozen=True)
class LogicalMasterValidation:
    pass_: bool
    status: str
    metrics: dict[str, Any]
    warnings: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "pass": self.pass_,
            "status": self.status,
            "metrics": self.metrics,
            "warnings": list(self.warnings),
        }


def _chroma_masks(rgb: np.ndarray) -> dict[str, np.ndarray]:
    red, green, blue = (rgb[:, :, index].astype(np.int16) for index in range(3))
    return {
        "magenta": (red >= 170) & (blue >= 170) & (green <= 115) & ((red - green) >= 70) & ((blue - green) >= 70),
        "green": (green >= 170) & (red <= 115) & (blue <= 115) & ((green - red) >= 70) & ((green - blue) >= 70),
    }


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


def _border_reference(rgb: np.ndarray) -> np.ndarray:
    border = np.concatenate((rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]), axis=0)
    quantised = (border // 16).astype(np.uint8)
    colours, counts = np.unique(quantised, axis=0, return_counts=True)
    return colours[int(np.argmax(counts))].astype(np.float32) * 16.0 + 8.0


def _background_mask(array: np.ndarray, tolerance: float) -> tuple[np.ndarray, str, dict[str, Any]]:
    rgb = array[:, :, :3]
    alpha = array[:, :, 3]
    opaque = alpha > 0
    total = max(1, rgb.shape[0] * rgb.shape[1])
    transparent = alpha == 0

    for key, mask in _chroma_masks(rgb).items():
        candidate = mask & opaque
        count = int(np.count_nonzero(candidate))
        if count >= max(16, int(total * 0.005)):
            connected = _border_connected(candidate)
            if np.any(connected):
                combined = transparent | connected
                mode = f"transparent+chroma:{key}" if np.any(transparent) else f"chroma:{key}"
                return combined, mode, {
                    "keyed_pixels": count,
                    "transparent_pixels": int(np.count_nonzero(transparent)),
                    "background_pixels": int(np.count_nonzero(combined)),
                }

    if np.any(transparent):
        return transparent, "transparent", {"background_pixels": int(np.count_nonzero(transparent))}

    reference = _border_reference(rgb)
    distance = np.sqrt(np.sum((rgb.astype(np.float32) - reference) ** 2, axis=2))
    candidate = (distance <= tolerance) & opaque
    if np.count_nonzero(candidate) < max(16, int(total * 0.05)):
        return np.zeros_like(opaque), "none", {"background_pixels": 0}
    connected = _border_connected(candidate)
    return connected, "border-flood", {"background_pixels": int(np.count_nonzero(connected))}


def remove_background(image: Image.Image, *, tolerance: float = 28.0) -> tuple[Image.Image, str, dict[str, Any]]:
    """Remove only transparent or border-connected background pixels."""

    array = np.asarray(image.convert("RGBA"), dtype=np.uint8).copy()
    mask, mode, stats = _background_mask(array, tolerance)
    array[mask] = (0, 0, 0, 0)
    return Image.fromarray(array, mode="RGBA"), mode, stats


def _subject_bbox(alpha: np.ndarray, threshold: int) -> tuple[int, int, int, int] | None:
    ys, xs = np.where(alpha >= threshold)
    if not len(xs):
        return None
    return int(xs.min()), int(ys.min()), int(xs.max() + 1), int(ys.max() + 1)


def _rgb_to_oklab(rgb: np.ndarray) -> np.ndarray:
    values = np.asarray(rgb, dtype=np.float32) / 255.0
    linear = np.where(values <= 0.04045, values / 12.92, ((values + 0.055) / 1.055) ** 2.4)
    lms = linear @ _RGB_TO_LMS.T
    lms = np.sign(lms) * np.abs(lms) ** (1.0 / 3.0)
    return lms @ _LMS_TO_LAB.T


def _cluster_palette(rgb: np.ndarray, requested: int | None, iterations: int) -> np.ndarray:
    pixels = rgb.reshape(-1, 3).astype(np.float32)
    if len(pixels) == 0:
        return np.zeros((0, 3), dtype=np.uint8)
    unique, counts = np.unique(pixels.astype(np.uint8), axis=0, return_counts=True)
    target = min(requested or DEFAULT_PALETTE_SIZE, len(unique))
    if target <= 0:
        return np.zeros((0, 3), dtype=np.uint8)
    sample_limit = 24000
    if len(pixels) > sample_limit:
        indices = np.linspace(0, len(pixels) - 1, sample_limit, dtype=np.int64)
        sample = pixels[indices]
    else:
        sample = pixels
    lab = _rgb_to_oklab(sample)
    sample_unique, sample_counts = np.unique(sample.astype(np.uint8), axis=0, return_counts=True)
    first_color = sample_unique[int(np.argmax(sample_counts))]
    first = int(np.flatnonzero(np.all(sample.astype(np.uint8) == first_color, axis=1))[0])
    centers = [lab[first]]
    distances = np.sum((lab - centers[0]) ** 2, axis=1)
    for _ in range(1, target):
        index = int(np.argmax(distances))
        centers.append(lab[index])
        distances = np.minimum(distances, np.sum((lab - centers[-1]) ** 2, axis=1))
    centers_array = np.asarray(centers, dtype=np.float32)
    for _ in range(iterations):
        distances = np.sum((lab[:, None, :] - centers_array[None, :, :]) ** 2, axis=2)
        labels = np.argmin(distances, axis=1)
        updated = centers_array.copy()
        for index in range(target):
            members = lab[labels == index]
            if len(members):
                updated[index] = members.mean(axis=0)
        if np.allclose(updated, centers_array, atol=1e-5):
            break
        centers_array = updated
    distances = np.sum((lab[:, None, :] - centers_array[None, :, :]) ** 2, axis=2)
    labels = np.argmin(distances, axis=1)
    palette = []
    sample_rgb = sample.astype(np.float32)
    for index in range(target):
        members = sample_rgb[labels == index]
        if len(members):
            palette.append(np.rint(members.mean(axis=0)).clip(0, 255).astype(np.uint8))
    if not palette:
        palette = [unique[0]]
    return np.unique(np.asarray(palette, dtype=np.uint8), axis=0)


def _assign_palette(rgb: np.ndarray, palette: np.ndarray) -> np.ndarray:
    pixels = rgb.reshape(-1, 3)
    if not len(palette):
        return np.zeros((rgb.shape[0], rgb.shape[1]), dtype=np.int16)
    palette_lab = _rgb_to_oklab(palette)
    labels = np.empty(len(pixels), dtype=np.int16)
    for start in range(0, len(pixels), 65536):
        stop = min(len(pixels), start + 65536)
        distances = np.sum(
            (_rgb_to_oklab(pixels[start:stop])[:, None, :] - palette_lab[None, :, :]) ** 2,
            axis=2,
        )
        labels[start:stop] = np.argmin(distances, axis=1)
    return labels.reshape(rgb.shape[:2])


def extract_structure(image: Image.Image, options: StructureExtractorOptions = StructureExtractorOptions()) -> StructureExtractionResult:
    """Project a semantic high-resolution image into a true logical grid."""

    cleaned, background_mode, background_stats = remove_background(
        image, tolerance=options.background_tolerance
    )
    array = np.asarray(cleaned.convert("RGBA"), dtype=np.uint8)
    bbox = _subject_bbox(array[:, :, 3], options.alpha_threshold)
    if bbox is None:
        report = {
            "kind": "pixel-structure-extractor",
            "version": PSE_VERSION,
            "status": "FAIL_SUBJECT",
            "input_size": list(image.size),
            "background": {"mode": background_mode, **background_stats},
        }
        return StructureExtractionResult(
            image=None,
            input_subject_bbox=None,
            palette=(),
            report=report,
            warnings=({"code": "FAIL_SUBJECT", "message": "No opaque subject was detected."},),
        )

    left, top, right, bottom = bbox
    crop = array[top:bottom, left:right]
    opaque = crop[:, :, 3] >= options.alpha_threshold
    if not np.any(opaque):
        warning = {"code": "FAIL_SUBJECT", "message": "Subject disappeared after background removal."}
        return StructureExtractionResult(None, bbox, (), {"status": "FAIL_SUBJECT"}, (warning,))

    target_height = options.target_height
    target_width = max(1, int(round(crop.shape[1] * target_height / crop.shape[0])))
    palette_rgb = _cluster_palette(crop[:, :, :3][opaque], options.palette_size, options.palette_iterations)
    labels = _assign_palette(crop[:, :, :3], palette_rgb)
    logical = np.zeros((target_height, target_width, 4), dtype=np.uint8)
    coverage_values: list[float] = []
    for y in range(target_height):
        y0 = (y * crop.shape[0]) // target_height
        y1 = max(y0 + 1, ((y + 1) * crop.shape[0]) // target_height)
        for x in range(target_width):
            x0 = (x * crop.shape[1]) // target_width
            x1 = max(x0 + 1, ((x + 1) * crop.shape[1]) // target_width)
            cell_opaque = opaque[y0:y1, x0:x1]
            coverage = float(np.count_nonzero(cell_opaque) / cell_opaque.size)
            coverage_values.append(coverage)
            if coverage < options.opaque_coverage_threshold:
                continue
            cell_labels = labels[y0:y1, x0:x1][cell_opaque]
            counts = np.bincount(cell_labels, minlength=len(palette_rgb))
            chosen = int(np.argmax(counts))
            logical[y, x, :3] = palette_rgb[chosen]
            logical[y, x, 3] = 255

    logical_image = Image.fromarray(logical, mode="RGBA")
    palette = tuple((*map(int, color), 255) for color in palette_rgb)
    warnings: list[dict[str, Any]] = []
    if background_mode == "none":
        warnings.append({"code": "WARN_BACKGROUND_UNPROVEN", "message": "No removable border/background color was proven."})
    report = {
        "kind": "pixel-structure-extractor",
        "version": PSE_VERSION,
        "status": "PASS_PSE",
        "input_size": list(image.size),
        "input_subject_bbox": list(bbox),
        "logical_size": list(logical_image.size),
        "target_height": target_height,
        "actual_height": logical_image.height,
        "logical_width": logical_image.width,
        "background": {"mode": background_mode, **background_stats},
        "palette": {"requested": options.palette_size or "auto", "colors": len(palette)},
        "projection": {
            "mode": "palette-cluster-weighted-mode",
            "opaque_coverage_threshold": options.opaque_coverage_threshold,
            "coverage_min": round(min(coverage_values), 6) if coverage_values else 0.0,
            "coverage_mean": round(float(np.mean(coverage_values)), 6) if coverage_values else 0.0,
            "resampling": None,
            "resize_rescue": options.resize_rescue,
            "palette_relaxation": options.palette_relaxation,
            "background_redetect_after_projection": options.background_redetect_after_projection,
            "remove_isolated_pixels": options.remove_isolated_pixels,
        },
        "warnings": warnings,
    }
    return StructureExtractionResult(logical_image, bbox, palette, report, tuple(warnings))


def _component_sizes(mask: np.ndarray) -> list[int]:
    height, width = mask.shape
    visited = np.zeros_like(mask, dtype=bool)
    sizes: list[int] = []
    for y in range(height):
        for x in range(width):
            if not mask[y, x] or visited[y, x]:
                continue
            queue: deque[tuple[int, int]] = deque([(x, y)])
            visited[y, x] = True
            size = 0
            while queue:
                cx, cy = queue.popleft()
                size += 1
                for nx, ny in ((cx - 1, cy), (cx + 1, cy), (cx, cy - 1), (cx, cy + 1)):
                    if 0 <= nx < width and 0 <= ny < height and mask[ny, nx] and not visited[ny, nx]:
                        visited[ny, nx] = True
                        queue.append((nx, ny))
            sizes.append(size)
    return sizes


def validate_logical_master(
    image: Image.Image,
    *,
    target_height: int = 128,
    alpha_threshold: int = 128,
    max_palette_size: int | None = DEFAULT_PALETTE_SIZE,
) -> LogicalMasterValidation:
    """Validate an extractor-owned logical image without transport assumptions."""

    require_logical_height(target_height)

    array = np.asarray(image.convert("RGBA"), dtype=np.uint8)
    alpha = array[:, :, 3]
    bbox = _subject_bbox(alpha, alpha_threshold)
    warnings: list[dict[str, Any]] = []
    unique_alpha = set(np.unique(alpha).tolist())
    binary_alpha = unique_alpha <= {0, 255}
    palette_size = len({tuple(color) for color in array[alpha >= alpha_threshold, :3].tolist()})
    subject_height = 0 if bbox is None else bbox[3] - bbox[1]
    components = _component_sizes(alpha >= alpha_threshold)
    isolated_pixels = sum(size for size in components if size <= 1)
    opaque_pixels = int(np.count_nonzero(alpha >= alpha_threshold))
    isolated_ratio = isolated_pixels / max(1, opaque_pixels)
    opaque_rgb = array[alpha >= alpha_threshold, :3]
    opaque_magenta = int(np.count_nonzero(
        (opaque_rgb[:, 0] >= 170)
        & (opaque_rgb[:, 2] >= 170)
        & (opaque_rgb[:, 1] <= 115)
        & ((opaque_rgb[:, 0] - opaque_rgb[:, 1]) >= 70)
        & ((opaque_rgb[:, 2] - opaque_rgb[:, 1]) >= 70)
    )) if len(opaque_rgb) else 0

    if image.height != target_height:
        warnings.append({"code": "logical-height-invalid", "message": f"Logical canvas height is {image.height}; expected {target_height}."})
    if bbox is None or subject_height != target_height:
        warnings.append({"code": "subject-height-invalid", "message": f"Logical subject height is {subject_height}; expected {target_height}."})
    if not binary_alpha:
        warnings.append({"code": "soft-alpha", "message": "Logical alpha contains values other than 0 or 255."})
    if max_palette_size is not None and palette_size > max_palette_size:
        warnings.append({"code": "palette-limit-exceeded", "message": f"Logical palette has {palette_size} colors; limit is {max_palette_size}."})
    if isolated_ratio > 0.05:
        warnings.append({"code": "isolated-noise-ratio", "message": f"Isolated opaque pixels are {isolated_ratio:.3f} of the subject."})

    passed = (
        image.height == target_height
        and bbox is not None
        and subject_height == target_height
        and binary_alpha
        and (max_palette_size is None or palette_size <= max_palette_size)
        and isolated_ratio <= 0.05
    )
    status = "PASS_LOGICAL_MASTER" if passed else "FAIL_LOGICAL_MASTER"
    metrics = {
        "size": list(image.size),
        "bbox": list(bbox) if bbox else None,
        "subject_height": subject_height,
        "binary_alpha": binary_alpha,
        "palette_size": palette_size,
        "max_palette_size": max_palette_size,
        "target_height": target_height,
        "actual_height": image.height,
        "logical_width": image.width,
        "opaque_magenta": opaque_magenta,
        "projection_warnings": [],
        "cleanup_mutated_dimensions": False,
        "isolated_pixels": isolated_pixels,
        "isolated_ratio": round(isolated_ratio, 6),
    }
    return LogicalMasterValidation(passed, status, metrics, tuple(warnings))


__all__ = [
    "DEFAULT_PALETTE_SIZE",
    "LogicalMasterValidation",
    "PSE_VERSION",
    "StructureExtractionResult",
    "StructureExtractorOptions",
    "extract_structure",
    "remove_background",
    "validate_logical_master",
]
