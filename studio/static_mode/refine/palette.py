# SPDX-License-Identifier: Apache-2.0
"""Static Mode palette control (spec §8.3).

Same Oklab machinery as Sprite Mode, different target. Sprite Mode optimises
for *stability across frames* — one palette so nothing flickers. Static Mode
optimises for *a single image read at full size*: large areas holding one tone,
background separating from objects, and a palette small enough to look
deliberate without collapsing texture into mud.

The extra move here is area weighting. A scene's colour importance is not
proportional to pixel count alone — a small bright lantern matters more than
another thousand pixels of sky — so entries are seeded from occurrence but the
report surfaces which entries carry almost no area, letting an operator cut the
palette instead of discovering later that four slots draw one shrub.
"""

from __future__ import annotations

from typing import Any, Sequence

import numpy as np
from PIL import Image

from studio.shared.color.oklab import nearest_index, rgb_to_oklab
from studio.shared.config import DitherSettings, PaletteSettings
from studio.shared.palette import apply_palette, build_palette, opaque_colors, palette_distance_report

from .dither import apply_dither


Color = tuple[int, int, int, int]


def build_scene_palette(image: Image.Image, settings: PaletteSettings, *, iterations: int = 6) -> tuple[Color, ...]:
    return build_palette([image], settings.colors, iterations=iterations)


def quantise_scene(
    image: Image.Image,
    palette: Sequence[Color],
    dither: DitherSettings,
) -> Image.Image:
    """Map a scene onto its palette, dithering only if the project asked for it."""
    if not palette:
        return image.convert("RGBA")
    if str(dither.mode).lower() == "off":
        return apply_palette(image, palette)
    return apply_dither(image, palette, dither)


def palette_usage(image: Image.Image, palette: Sequence[Color]) -> dict[str, Any]:
    """Which palette entries actually carry area, and how much."""
    if not palette:
        return {"colors": 0, "usage": [], "unused": []}
    colors, counts = opaque_colors([image])
    if colors.shape[0] == 0:
        return {"colors": len(palette), "usage": [], "unused": list(range(len(palette)))}
    entries = np.asarray([[c[0], c[1], c[2]] for c in palette], dtype=np.uint8)
    index = nearest_index(rgb_to_oklab(colors), rgb_to_oklab(entries))
    totals = np.bincount(index, weights=counts.astype(np.float64), minlength=len(palette))
    share = totals / max(1.0, totals.sum())
    return {
        "colors": len(palette),
        "usage": [
            {"index": position, "color": list(palette[position])[:3], "share": round(float(share[position]), 6)}
            for position in range(len(palette))
        ],
        "unused": [position for position in range(len(palette)) if totals[position] <= 0],
        "separation": palette_distance_report(palette),
    }


def tone_consistency(image: Image.Image, *, block: int = 16) -> dict[str, Any]:
    """How uniform large areas are — the readability signal for §7.5.

    Measured as the mean Oklab spread inside coarse blocks. A quantised scene
    that still shows high within-block spread is one where texture survived
    where flat colour was wanted (or where dither was applied too hard).
    """
    array = np.asarray(image.convert("RGBA"), dtype=np.uint8)
    height, width, _ = array.shape
    if height < block or width < block:
        return {"block": block, "mean_spread": None, "blocks": 0}
    lab = rgb_to_oklab(array[:, :, :3])
    opaque = array[:, :, 3] >= 128
    spreads: list[float] = []
    for y in range(0, height - block + 1, block):
        for x in range(0, width - block + 1, block):
            mask = opaque[y : y + block, x : x + block]
            if mask.sum() < 4:
                continue
            patch = lab[y : y + block, x : x + block][mask]
            spreads.append(float(np.mean(np.std(patch, axis=0))))
    if not spreads:
        return {"block": block, "mean_spread": None, "blocks": 0}
    return {
        "block": block,
        "mean_spread": round(float(np.mean(spreads)), 6),
        "max_spread": round(float(np.max(spreads)), 6),
        "blocks": len(spreads),
    }
