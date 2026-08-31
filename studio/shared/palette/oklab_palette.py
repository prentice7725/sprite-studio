# SPDX-License-Identifier: Apache-2.0
"""Shared palette build/remap in Oklab (spec §5.5, §8.3).

Both modes quantise, but for different reasons: Sprite Mode wants one palette
across an animation so nothing flickers, Static Mode wants large flat areas to
survive simplification. Both want the same distance space, and that is the
whole reason this lives in Shared Core: a palette built with an RGB metric and
consulted with an Oklab one produces remaps that look wrong at exactly the
colours a character cares about (skin, metal, dark outlines).

Weighted k-means, deterministic: the seeding is farthest-point from a fixed
start (the heaviest colour), so the same frames always produce the same
palette. No RNG, no per-run drift.
"""

from __future__ import annotations

from typing import Any, Iterable, Sequence

import numpy as np
from PIL import Image

from studio.shared.color.oklab import nearest_index, oklab_to_rgb, rgb_to_oklab


Color = tuple[int, int, int, int]


def opaque_colors(images: Iterable[Image.Image], *, alpha_threshold: int = 128) -> tuple[np.ndarray, np.ndarray]:
    """Unique opaque RGB colours across images, with occurrence counts."""
    stacks: list[np.ndarray] = []
    for image in images:
        array = np.asarray(image.convert("RGBA"), dtype=np.uint8).reshape(-1, 4)
        stacks.append(array[array[:, 3] >= alpha_threshold][:, :3])
    if not stacks:
        return np.zeros((0, 3), dtype=np.uint8), np.zeros((0,), dtype=np.int64)
    pixels = np.concatenate(stacks, axis=0)
    if pixels.size == 0:
        return np.zeros((0, 3), dtype=np.uint8), np.zeros((0,), dtype=np.int64)
    colors, counts = np.unique(pixels, axis=0, return_counts=True)
    return colors, counts


def _seed_centroids(points: np.ndarray, weights: np.ndarray, k: int) -> np.ndarray:
    """Farthest-point seeding from the heaviest colour — deterministic k-means++."""
    seeds = [points[int(np.argmax(weights))]]
    if k == 1:
        return np.asarray(seeds)
    distances = np.sum((points - seeds[0]) ** 2, axis=1)
    while len(seeds) < k:
        # Weight the spread by occurrence so a single stray anti-aliased pixel
        # cannot claim a palette slot that a large flat area needs.
        index = int(np.argmax(distances * weights))
        if distances[index] <= 0:
            break
        seeds.append(points[index])
        distances = np.minimum(distances, np.sum((points - points[index]) ** 2, axis=1))
    return np.asarray(seeds)


def build_palette(
    images: Sequence[Image.Image],
    colors: int,
    *,
    alpha_threshold: int = 128,
    iterations: int = 6,
) -> tuple[Color, ...]:
    """One shared palette for a whole frame set / scene, chosen in Oklab."""
    if colors < 1:
        raise ValueError("palette size must be at least 1")
    unique, counts = opaque_colors(images, alpha_threshold=alpha_threshold)
    if unique.shape[0] == 0:
        return ()
    if unique.shape[0] <= colors:
        order = np.argsort(-counts)
        return tuple((int(r), int(g), int(b), 255) for r, g, b in unique[order])
    points = rgb_to_oklab(unique)
    weights = counts.astype(np.float64)
    centroids = _seed_centroids(points, weights, colors)
    for _ in range(max(1, iterations)):
        assignment = nearest_index(points, centroids)
        moved = np.zeros_like(centroids)
        for index in range(centroids.shape[0]):
            members = assignment == index
            weight = weights[members].sum()
            if weight <= 0:
                moved[index] = centroids[index]
                continue
            moved[index] = (points[members] * weights[members, None]).sum(axis=0) / weight
        if np.allclose(moved, centroids, atol=1e-9):
            centroids = moved
            break
        centroids = moved
    rgb = oklab_to_rgb(centroids)
    # Snap each centroid to the nearest colour that actually occurs. A centroid is
    # an average and can land on a colour the artwork never contained; snapping
    # keeps the palette inside the source gamut so a remap cannot invent a hue.
    snapped = unique[nearest_index(rgb_to_oklab(rgb), points)]
    deduped: list[Color] = []
    for entry in snapped:
        color = (int(entry[0]), int(entry[1]), int(entry[2]), 255)
        if color not in deduped:
            deduped.append(color)
    return tuple(deduped)


def apply_palette(
    image: Image.Image,
    palette: Sequence[Color],
    *,
    alpha_threshold: int = 128,
) -> Image.Image:
    """Remap every opaque pixel to its nearest palette entry in Oklab."""
    if not palette:
        return image.convert("RGBA")
    source = np.asarray(image.convert("RGBA"), dtype=np.uint8)
    height, width, _ = source.shape
    flat = source.reshape(-1, 4)
    opaque = flat[:, 3] >= alpha_threshold
    result = np.zeros_like(flat)
    if opaque.any():
        entries = np.asarray([[c[0], c[1], c[2]] for c in palette], dtype=np.uint8)
        index = nearest_index(rgb_to_oklab(flat[opaque][:, :3]), rgb_to_oklab(entries))
        result[opaque, :3] = entries[index]
        result[opaque, 3] = 255
    return Image.fromarray(result.reshape(height, width, 4), mode="RGBA")


def palette_distance_report(palette: Sequence[Color]) -> dict[str, Any]:
    """Minimum separation inside a palette — how much room a remap has to be wrong.

    A pair of entries closer than roughly 0.02 in Oklab is invisible at runtime,
    which means the two slots are effectively one and the palette is smaller
    than it claims. Surfaced, never auto-merged.
    """
    if len(palette) < 2:
        return {"colors": len(palette), "min_delta_e": None, "closest_pair": None}
    points = rgb_to_oklab(np.asarray([[c[0], c[1], c[2]] for c in palette], dtype=np.uint8))
    distances = np.sqrt(np.sum((points[:, None, :] - points[None, :, :]) ** 2, axis=2))
    np.fill_diagonal(distances, np.inf)
    index = int(np.argmin(distances))
    row, column = divmod(index, distances.shape[1])
    return {
        "colors": len(palette),
        "min_delta_e": round(float(distances[row, column]), 6),
        "closest_pair": [list(palette[row])[:3], list(palette[column])[:3]],
    }
