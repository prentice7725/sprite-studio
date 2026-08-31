# SPDX-License-Identifier: MIT
"""Dithering — Static Mode only, and off by default (spec §8.4).

The policy matters more than the algorithm:

* character sprites: **OFF**. Dither on a 48×48 unit is noise that reads as
  damage at runtime and destroys the flat colour regions a palette swap needs.
* ground, walls, environment texture: optional.
* moody still scenes: optional.

That is why this module lives under ``static_mode`` and not in Shared Core.
Sprite Mode cannot reach it, so "just this once on a character" is not a
decision anyone can make by accident.

Error is diffused in linear light (where an averaged error means what it says)
while the nearest palette entry is chosen in Oklab (where "nearest" means what
a viewer sees) — mixing those up is how a diffused error slowly drifts hue.
"""

from __future__ import annotations

from typing import Sequence

import numpy as np
from PIL import Image

from studio.shared.color.oklab import linear_to_srgb, nearest_index, rgb_to_oklab, srgb_to_linear
from studio.shared.config import DitherSettings


Color = tuple[int, int, int, int]
DITHER_MODES = ("off", "ordered", "serpentine")


def _bayer(size: int) -> np.ndarray:
    """Normalised Bayer threshold matrix of side ``size`` (a power of two)."""
    if size < 2 or size & (size - 1):
        raise ValueError("dither.matrix must be a power of two of at least 2")
    matrix = np.array([[0, 2], [3, 1]], dtype=np.float64)
    while matrix.shape[0] < size:
        matrix = np.block(
            [
                [4 * matrix, 4 * matrix + 2],
                [4 * matrix + 3, 4 * matrix + 1],
            ]
        )
    return matrix / matrix.size - 0.5


def _palette_arrays(palette: Sequence[Color]) -> tuple[np.ndarray, np.ndarray]:
    entries = np.asarray([[c[0], c[1], c[2]] for c in palette], dtype=np.uint8)
    return entries, rgb_to_oklab(entries)


def apply_dither(
    image: Image.Image,
    palette: Sequence[Color],
    settings: DitherSettings,
    *,
    alpha_threshold: int = 128,
) -> Image.Image:
    """Quantise to ``palette`` using the configured dither mode."""
    mode = str(settings.mode).lower()
    if mode not in DITHER_MODES:
        raise ValueError(f"dither.mode must be one of {DITHER_MODES} (got {settings.mode!r})")
    if mode == "off" or not palette:
        from studio.shared.palette import apply_palette

        return apply_palette(image, palette, alpha_threshold=alpha_threshold)
    if mode == "ordered":
        return _ordered(image, palette, settings, alpha_threshold)
    return _serpentine(image, palette, settings, alpha_threshold)


def _ordered(image: Image.Image, palette: Sequence[Color], settings: DitherSettings, alpha_threshold: int) -> Image.Image:
    source = np.asarray(image.convert("RGBA"), dtype=np.uint8)
    height, width, _ = source.shape
    entries, palette_lab = _palette_arrays(palette)
    threshold = _bayer(int(settings.matrix))
    tile = np.tile(threshold, (height // threshold.shape[0] + 1, width // threshold.shape[1] + 1))[:height, :width]

    # The perturbation is scaled by the palette's own coarseness: a 4-colour
    # palette needs a much larger nudge to reach a neighbouring entry than a
    # 64-colour one, and a fixed offset would be invisible in one and garish in
    # the other.
    spread = _palette_spread(palette_lab) * float(settings.strength)
    linear = srgb_to_linear(source[:, :, :3].astype(np.float64) / 255.0)
    nudged = np.clip(linear + (tile * spread)[:, :, None], 0.0, 1.0)
    rgb = np.clip(np.rint(linear_to_srgb(nudged) * 255.0), 0, 255).astype(np.uint8)

    flat = rgb.reshape(-1, 3)
    index = nearest_index(rgb_to_oklab(flat), palette_lab)
    result = np.zeros((height * width, 4), dtype=np.uint8)
    opaque = source[:, :, 3].reshape(-1) >= alpha_threshold
    result[opaque, :3] = entries[index][opaque]
    result[opaque, 3] = 255
    return Image.fromarray(result.reshape(height, width, 4), mode="RGBA")


def _palette_spread(palette_lab: np.ndarray) -> float:
    if palette_lab.shape[0] < 2:
        return 0.0
    distances = np.sqrt(np.sum((palette_lab[:, None, :] - palette_lab[None, :, :]) ** 2, axis=2))
    np.fill_diagonal(distances, np.inf)
    return float(np.median(np.min(distances, axis=1)))


def _serpentine(image: Image.Image, palette: Sequence[Color], settings: DitherSettings, alpha_threshold: int) -> Image.Image:
    """Floyd–Steinberg with alternating row direction.

    Serpentine ordering exists to break the diagonal worming that left-to-right
    diffusion produces on large flat areas — which is precisely what Static Mode
    has a lot of (skies, walls, ground).
    """
    source = np.asarray(image.convert("RGBA"), dtype=np.uint8)
    height, width, _ = source.shape
    entries, palette_lab = _palette_arrays(palette)
    alpha = source[:, :, 3]
    opaque = alpha >= alpha_threshold
    work = srgb_to_linear(source[:, :, :3].astype(np.float64) / 255.0)
    palette_linear = srgb_to_linear(entries.astype(np.float64) / 255.0)
    output = np.zeros((height, width, 4), dtype=np.uint8)
    strength = float(np.clip(settings.strength, 0.0, 1.0))

    for y in range(height):
        columns = range(width) if y % 2 == 0 else range(width - 1, -1, -1)
        step = 1 if y % 2 == 0 else -1
        for x in columns:
            if not opaque[y, x]:
                continue
            current = np.clip(work[y, x], 0.0, 1.0)
            srgb = np.clip(np.rint(linear_to_srgb(current) * 255.0), 0, 255).astype(np.uint8)
            choice = int(nearest_index(rgb_to_oklab(srgb.reshape(1, 3)), palette_lab)[0])
            output[y, x, :3] = entries[choice]
            output[y, x, 3] = 255
            error = (current - palette_linear[choice]) * strength
            for dx, dy, weight in ((step, 0, 7 / 16), (-step, 1, 3 / 16), (0, 1, 5 / 16), (step, 1, 1 / 16)):
                nx, ny = x + dx, y + dy
                if 0 <= nx < width and 0 <= ny < height and opaque[ny, nx]:
                    work[ny, nx] += error * weight
    return Image.fromarray(output, mode="RGBA")
