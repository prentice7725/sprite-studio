# SPDX-License-Identifier: Apache-2.0
"""Scene cleanup / Static Repair (spec §7.3, §8.1).

Static Mode's repair is not Sprite Mode's. There are no neighbouring frames to
vote, no thin weapon to reconstruct, no temporal evidence at all — one image
either reads or it does not. What is left is bounded and local:

* **orphan specks** — a handful of stray opaque pixels floating clear of every
  real region, usually chroma-key residue.
* **fringe** — semi-transparent anti-aliased rims that turn into halos the
  moment the asset is composited over a different background.
* **hole fill** — fully-enclosed transparent pockets inside a solid region.

Every operation here is deterministic and reports what it touched. Nothing
guesses at content: a hole is filled from the colours that already surround it,
never invented.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from PIL import Image

from studio.shared.config import CleanupSettings


@dataclass(frozen=True)
class CleanupResult:
    image: Image.Image
    report: dict[str, Any]


def label_components(mask: np.ndarray) -> tuple[np.ndarray, int]:
    """4-connected labelling via iterative propagation. No SciPy dependency.

    Each pixel starts as its own id and repeatedly takes the minimum of its
    4-neighbourhood; the sweep is bounded by the longest path in a component,
    which for the speck-sized regions this module cares about is a few passes.
    """
    height, width = mask.shape
    labels = np.where(mask, np.arange(mask.size, dtype=np.int64).reshape(height, width), -1)
    while True:
        previous = labels
        candidate = labels.copy()
        for shift, axis in ((1, 0), (-1, 0), (1, 1), (-1, 1)):
            rolled = np.roll(labels, shift, axis=axis)
            if axis == 0:
                if shift == 1:
                    rolled[0, :] = -1
                else:
                    rolled[-1, :] = -1
            else:
                if shift == 1:
                    rolled[:, 0] = -1
                else:
                    rolled[:, -1] = -1
            valid = mask & (rolled >= 0)
            candidate = np.where(valid & ((candidate < 0) | (rolled < candidate)), rolled, candidate)
        candidate = np.where(mask, np.minimum(candidate, labels), -1)
        if np.array_equal(candidate, previous):
            break
        labels = candidate
    unique = np.unique(labels[labels >= 0])
    remap = {value: index for index, value in enumerate(unique)}
    output = np.full(labels.shape, -1, dtype=np.int64)
    for value, index in remap.items():
        output[labels == value] = index
    return output, len(unique)


def remove_orphans(image: Image.Image, settings: CleanupSettings) -> CleanupResult:
    """Drop opaque components at or below ``orphan_max_area`` pixels."""
    array = np.asarray(image.convert("RGBA"), dtype=np.uint8).copy()
    mask = array[:, :, 3] >= settings.fringe_alpha_threshold
    if not mask.any() or settings.orphan_max_area <= 0:
        return CleanupResult(Image.fromarray(array, mode="RGBA"), {"removed_components": 0, "removed_pixels": 0})
    labels, count = label_components(mask)
    removed_components = 0
    removed_pixels = 0
    if count:
        sizes = np.bincount(labels[labels >= 0], minlength=count)
        small = np.flatnonzero(sizes <= settings.orphan_max_area)
        if small.size:
            drop = np.isin(labels, small)
            removed_components = int(small.size)
            removed_pixels = int(np.count_nonzero(drop))
            array[drop] = (0, 0, 0, 0)
    return CleanupResult(
        Image.fromarray(array, mode="RGBA"),
        {"removed_components": removed_components, "removed_pixels": removed_pixels, "components": int(count)},
    )


def harden_alpha(image: Image.Image, settings: CleanupSettings) -> CleanupResult:
    """Binarise alpha at the threshold — no semi-transparent fringe survives."""
    array = np.asarray(image.convert("RGBA"), dtype=np.uint8).copy()
    alpha = array[:, :, 3]
    soft = int(np.count_nonzero((alpha > 0) & (alpha < 255)))
    keep = alpha >= settings.fringe_alpha_threshold
    array[~keep] = (0, 0, 0, 0)
    array[keep, 3] = 255
    return CleanupResult(Image.fromarray(array, mode="RGBA"), {"softened_pixels": soft, "kept_pixels": int(keep.sum())})


def fill_holes(image: Image.Image, *, max_area: int = 4) -> CleanupResult:
    """Fill small fully-enclosed transparent pockets with their surrounding colour.

    "Enclosed" is decided by connectivity to the image border, so a transparent
    region that reaches the edge — the actual background — is never touched.
    """
    array = np.asarray(image.convert("RGBA"), dtype=np.uint8).copy()
    transparent = array[:, :, 3] < 128
    if not transparent.any():
        return CleanupResult(Image.fromarray(array, mode="RGBA"), {"filled_regions": 0, "filled_pixels": 0})
    labels, count = label_components(transparent)
    if not count:
        return CleanupResult(Image.fromarray(array, mode="RGBA"), {"filled_regions": 0, "filled_pixels": 0})
    border = set(labels[0, :].tolist()) | set(labels[-1, :].tolist()) | set(labels[:, 0].tolist()) | set(labels[:, -1].tolist())
    sizes = np.bincount(labels[labels >= 0], minlength=count)
    filled_regions = 0
    filled_pixels = 0
    for region in range(count):
        if region in border or sizes[region] > max_area:
            continue
        pocket = labels == region
        neighbours = _dilate(pocket) & ~pocket & (array[:, :, 3] >= 128)
        if not neighbours.any():
            continue
        colors = array[neighbours][:, :3]
        values, counts = np.unique(colors, axis=0, return_counts=True)
        array[pocket, :3] = values[int(np.argmax(counts))]
        array[pocket, 3] = 255
        filled_regions += 1
        filled_pixels += int(pocket.sum())
    return CleanupResult(
        Image.fromarray(array, mode="RGBA"),
        {"filled_regions": filled_regions, "filled_pixels": filled_pixels},
    )


def _dilate(mask: np.ndarray) -> np.ndarray:
    grown = mask.copy()
    grown[1:, :] |= mask[:-1, :]
    grown[:-1, :] |= mask[1:, :]
    grown[:, 1:] |= mask[:, :-1]
    grown[:, :-1] |= mask[:, 1:]
    return grown


def cleanup_scene(image: Image.Image, settings: CleanupSettings, *, fill_max_area: int = 4) -> CleanupResult:
    """Run the whole static cleanup pass and report each stage."""
    hardened = harden_alpha(image, settings)
    orphaned = remove_orphans(hardened.image, settings)
    filled = fill_holes(orphaned.image, max_area=fill_max_area)
    return CleanupResult(
        filled.image,
        {
            "kind": "asset-studio-static-cleanup",
            "alpha": hardened.report,
            "orphans": orphaned.report,
            "holes": filled.report,
        },
    )
