# SPDX-License-Identifier: Apache-2.0
"""Layer split and object cutout (spec §7.4, §8.1).

Two related jobs Static Mode has and Sprite Mode does not:

* **cutout** — pull a prop off its background cleanly enough to drop into a
  scene. The background is identified from the border, not from a colour the
  operator guesses at, because a generated prop sheet rarely uses the exact
  chroma value anybody typed.
* **layer split** — separate a scene into background / midground / foreground
  so they can be parallaxed or re-composited. Depth is not recoverable from a
  flat image, so this splits on evidence that actually exists: how much of the
  border a region touches, and how large it is.

Both label rather than invent. A split returns masks over the original pixels;
nothing is repainted, so re-composing every layer reproduces the input exactly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np
from PIL import Image

from studio.shared.color.oklab import rgb_to_oklab

from studio.static_mode.cleanup.scene_cleanup import label_components


@dataclass(frozen=True)
class Layer:
    name: str
    image: Image.Image
    pixels: int
    touches_border: bool

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "pixels": self.pixels, "touches_border": self.touches_border}


def _border_colors(array: np.ndarray) -> np.ndarray:
    border = np.concatenate(
        [array[0, :, :3], array[-1, :, :3], array[:, 0, :3], array[:, -1, :3]], axis=0
    )
    values, counts = np.unique(border, axis=0, return_counts=True)
    return values[np.argsort(-counts)]


def cutout_object(image: Image.Image, *, tolerance: float = 0.06, keep_largest: bool = True) -> tuple[Image.Image, dict[str, Any]]:
    """Remove the background and keep the object.

    ``tolerance`` is an Oklab distance, so it means the same thing on a pale sky
    and a dark cave wall — an RGB tolerance would cut one and miss the other.
    """
    array = np.asarray(image.convert("RGBA"), dtype=np.uint8).copy()
    height, width, _ = array.shape
    dominant = _border_colors(array)[0]
    lab = rgb_to_oklab(array[:, :, :3])
    background = np.sqrt(np.sum((lab - rgb_to_oklab(dominant)) ** 2, axis=-1)) <= tolerance

    # Only background *connected to the border* is removed. A patch of sky-coloured
    # pixels enclosed inside the object is part of the object (a window, a gem)
    # and deleting it would punch a hole through the cutout.
    labels, count = label_components(background)
    reachable = set()
    if count:
        for edge in (labels[0, :], labels[-1, :], labels[:, 0], labels[:, -1]):
            reachable |= {int(value) for value in np.unique(edge) if value >= 0}
    removed = np.isin(labels, list(reachable)) if reachable else np.zeros_like(background)
    array[removed] = (0, 0, 0, 0)

    kept = array[:, :, 3] >= 128
    components = 0
    if keep_largest and kept.any():
        object_labels, components = label_components(kept)
        if components > 1:
            sizes = np.bincount(object_labels[object_labels >= 0], minlength=components)
            biggest = int(np.argmax(sizes))
            array[(object_labels >= 0) & (object_labels != biggest)] = (0, 0, 0, 0)
    result = Image.fromarray(array, mode="RGBA")
    return result, {
        "kind": "asset-studio-cutout",
        "background_color": [int(value) for value in dominant],
        "tolerance": tolerance,
        "removed_pixels": int(np.count_nonzero(removed)),
        "kept_pixels": int(np.count_nonzero(array[:, :, 3] >= 128)),
        "object_components": int(components),
    }


def split_layers(image: Image.Image, *, min_pixels: int = 16) -> tuple[list[Layer], dict[str, Any]]:
    """Split a scene into background / midground / foreground masks.

    The heuristic, stated plainly so nobody mistakes it for depth estimation:
    regions touching the image border and covering a large share of it are
    background; large interior regions are midground; everything else that is
    big enough to matter is foreground.
    """
    array = np.asarray(image.convert("RGBA"), dtype=np.uint8)
    height, width, _ = array.shape
    opaque = array[:, :, 3] >= 128
    if not opaque.any():
        return [], {"kind": "asset-studio-layer-split", "layers": [], "regions": 0}

    # Region membership is by colour, then by connectivity: a scene's flat areas
    # are exactly what a quantised static image is made of, so equal-colour
    # connected regions are the natural unit here.
    colors = array[:, :, :3].reshape(-1, 3)
    unique, inverse = np.unique(colors, axis=0, return_inverse=True)
    inverse = inverse.reshape(height, width)

    assignments: dict[str, np.ndarray] = {
        "background": np.zeros((height, width), dtype=bool),
        "midground": np.zeros((height, width), dtype=bool),
        "foreground": np.zeros((height, width), dtype=bool),
    }
    regions = 0
    for index in range(unique.shape[0]):
        mask = (inverse == index) & opaque
        if not mask.any():
            continue
        labels, count = label_components(mask)
        for region in range(count):
            piece = labels == region
            size = int(piece.sum())
            if size < min_pixels:
                assignments["foreground"] |= piece
                continue
            regions += 1
            touches = bool(piece[0, :].any() or piece[-1, :].any() or piece[:, 0].any() or piece[:, -1].any())
            share = size / float(height * width)
            if touches and share >= 0.08:
                assignments["background"] |= piece
            elif share >= 0.02:
                assignments["midground"] |= piece
            else:
                assignments["foreground"] |= piece

    layers: list[Layer] = []
    for name in ("background", "midground", "foreground"):
        mask = assignments[name]
        if not mask.any():
            continue
        layer_array = np.zeros_like(array)
        layer_array[mask] = array[mask]
        layers.append(
            Layer(
                name=name,
                image=Image.fromarray(layer_array, mode="RGBA"),
                pixels=int(mask.sum()),
                touches_border=bool(mask[0, :].any() or mask[-1, :].any() or mask[:, 0].any() or mask[:, -1].any()),
            )
        )
    return layers, {
        "kind": "asset-studio-layer-split",
        "layers": [layer.to_dict() for layer in layers],
        "regions": regions,
    }


def compose_layers(layers: Sequence[Layer], size: tuple[int, int]) -> Image.Image:
    """Re-stack a split. Round-trips to the input, which is the split's own test."""
    canvas = Image.new("RGBA", size, (0, 0, 0, 0))
    for layer in layers:
        canvas.alpha_composite(layer.image)
    return canvas
