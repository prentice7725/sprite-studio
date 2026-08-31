# SPDX-License-Identifier: MIT
"""Tile / seam-aware processing (spec §8.6).

A tile is judged at its edges. When it repeats, the right column sits against
the left column and the bottom row against the top; whatever discontinuity
exists there becomes a visible grid line across the whole floor, and it is
invisible while looking at the tile on its own.

So the check compares the wrap partners directly, in Oklab, and reports a
per-edge score plus the worst offending positions. Repair is offered but never
automatic: averaging a seam flat is a real edit to the artwork, and on a tile
where the mismatch is a deliberate feature (a wall meeting a floor) it is the
wrong answer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from PIL import Image

from studio.shared.color.oklab import rgb_to_oklab
from studio.shared.config import SeamSettings


@dataclass(frozen=True)
class SeamReport:
    horizontal: float
    vertical: float
    threshold: float
    ok: bool
    worst: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "asset-studio-seam-report",
            "horizontal_delta_e": round(self.horizontal, 6),
            "vertical_delta_e": round(self.vertical, 6),
            "threshold": self.threshold,
            "ok": self.ok,
            "worst": self.worst,
        }


def _band(array: np.ndarray, edge: str, band: int) -> np.ndarray:
    if edge == "left":
        return array[:, :band]
    if edge == "right":
        return array[:, -band:]
    if edge == "top":
        return array[:band, :]
    return array[-band:, :]


def check_seams(image: Image.Image, settings: SeamSettings) -> SeamReport:
    """Compare each edge with the edge it meets when the tile repeats."""
    array = np.asarray(image.convert("RGBA"), dtype=np.uint8)
    band = max(1, int(settings.band))
    height, width, _ = array.shape
    if width < band * 2 or height < band * 2:
        raise ValueError("image is too small for the configured seam band")

    left = rgb_to_oklab(_band(array, "left", band)[:, :, :3])
    right = rgb_to_oklab(_band(array, "right", band)[:, :, :3])
    top = rgb_to_oklab(_band(array, "top", band)[:, :, :3])
    bottom = rgb_to_oklab(_band(array, "bottom", band)[:, :, :3])

    # Right meets left and bottom meets top; the comparison is between the
    # outermost column/row of each side, which is what actually abuts on repeat.
    horizontal_delta = np.sqrt(np.sum((right[:, -1, :] - left[:, 0, :]) ** 2, axis=-1))
    vertical_delta = np.sqrt(np.sum((bottom[-1, :, :] - top[0, :, :]) ** 2, axis=-1))

    # Alpha discontinuity is a seam too: an opaque edge meeting a transparent one
    # tiles as a hole, and a colour-only metric would score it a perfect zero.
    alpha_h = (array[:, -1, 3] >= 128) != (array[:, 0, 3] >= 128)
    alpha_v = (array[-1, :, 3] >= 128) != (array[0, :, 3] >= 128)
    horizontal_delta = np.where(alpha_h, np.maximum(horizontal_delta, 1.0), horizontal_delta)
    vertical_delta = np.where(alpha_v, np.maximum(vertical_delta, 1.0), vertical_delta)

    horizontal = float(np.mean(horizontal_delta))
    vertical = float(np.mean(vertical_delta))
    worst = {
        "horizontal_row": int(np.argmax(horizontal_delta)),
        "horizontal_delta_e": round(float(np.max(horizontal_delta)), 6),
        "vertical_column": int(np.argmax(vertical_delta)),
        "vertical_delta_e": round(float(np.max(vertical_delta)), 6),
    }
    return SeamReport(
        horizontal=horizontal,
        vertical=vertical,
        threshold=float(settings.threshold),
        ok=horizontal <= settings.threshold and vertical <= settings.threshold,
        worst=worst,
    )


def wraparound_preview(image: Image.Image, *, repeat: int = 2, offset: bool = True) -> Image.Image:
    """Tile the image so a seam becomes visible where it actually shows up.

    Offsetting the second row by half a tile is what exposes vertical seams; a
    plain 2×2 grid hides them behind their own repetition.
    """
    source = image.convert("RGBA")
    width, height = source.size
    canvas = Image.new("RGBA", (width * repeat, height * repeat), (0, 0, 0, 0))
    for row in range(repeat):
        shift = (width // 2) if (offset and row % 2) else 0
        for column in range(-1, repeat + 1):
            canvas.alpha_composite(source, (column * width + shift, row * height))
    return canvas


def repair_seams(image: Image.Image, settings: SeamSettings) -> tuple[Image.Image, dict[str, Any]]:
    """Average the wrap partners into each other so the tile closes.

    Symmetric by construction — both sides move halfway — because moving only
    one side shifts the tile's content relative to its own grid and shows up as
    a bias the next time the tile is scored.
    """
    array = np.asarray(image.convert("RGBA"), dtype=np.uint8).astype(np.float64)
    height, width, _ = array.shape
    touched = 0
    both_opaque_h = (array[:, 0, 3] >= 128) & (array[:, -1, 3] >= 128)
    if both_opaque_h.any():
        average = (array[both_opaque_h, 0, :3] + array[both_opaque_h, -1, :3]) / 2.0
        array[both_opaque_h, 0, :3] = average
        array[both_opaque_h, -1, :3] = average
        touched += int(both_opaque_h.sum())
    both_opaque_v = (array[0, :, 3] >= 128) & (array[-1, :, 3] >= 128)
    if both_opaque_v.any():
        average = (array[0, both_opaque_v, :3] + array[-1, both_opaque_v, :3]) / 2.0
        array[0, both_opaque_v, :3] = average
        array[-1, both_opaque_v, :3] = average
        touched += int(both_opaque_v.sum())
    repaired = Image.fromarray(np.clip(np.rint(array), 0, 255).astype(np.uint8), mode="RGBA")
    after = check_seams(repaired, settings)
    return repaired, {"blended_pixels": touched, "after": after.to_dict()}
