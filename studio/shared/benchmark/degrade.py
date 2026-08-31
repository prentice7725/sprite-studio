# SPDX-License-Identifier: MIT
"""Synthetic degradation (spec §9.3).

The benchmark's premise: take art we know is correct, break it the way an image
generator breaks it, and measure whether refine and repair put it back. That
only works if the breakage is *representative* — which is why each degradation
below names the real failure it imitates rather than being a generic filter.

Every operation is seeded and deterministic. A benchmark whose inputs move
cannot tell an algorithm regression from a different random draw.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import numpy as np
from PIL import Image, ImageFilter

from studio.shared.color.oklab import linear_to_srgb, srgb_to_linear


@dataclass(frozen=True)
class Degradation:
    name: str
    apply: Callable[[Image.Image, float, np.random.Generator], Image.Image]
    description: str


def _rgba(image: Image.Image) -> np.ndarray:
    return np.asarray(image.convert("RGBA"), dtype=np.uint8)


def blur(image: Image.Image, strength: float, rng: np.random.Generator) -> Image.Image:
    """Soft output — the model drew a painting where dots were asked for."""
    return image.convert("RGBA").filter(ImageFilter.GaussianBlur(radius=max(0.1, strength * 2.0)))


def subpixel_offset(image: Image.Image, strength: float, rng: np.random.Generator) -> Image.Image:
    """The art sits between grid lines, so every cell straddles two blocks.

    This is the single most common reason a generated sprite refuses to snap:
    nothing is wrong with the drawing, it is just not aligned to any integer
    lattice.
    """
    shift = strength * 0.5
    return image.convert("RGBA").transform(
        image.size, Image.Transform.AFFINE, (1, 0, shift, 0, 1, shift), resample=Image.Resampling.BILINEAR
    )


def antialiased_resize(image: Image.Image, strength: float, rng: np.random.Generator) -> Image.Image:
    """Round-trip through a non-integer size with a smoothing filter.

    The classic "it was pixel art until someone resized it" damage: block edges
    become ramps and the true pitch stops being an integer.
    """
    width, height = image.size
    factor = 1.0 - 0.35 * strength
    intermediate = (max(4, int(width * factor)), max(4, int(height * factor)))
    return (
        image.convert("RGBA")
        .resize(intermediate, Image.Resampling.LANCZOS)
        .resize((width, height), Image.Resampling.BICUBIC)
    )


def pseudo_pixel_alias(image: Image.Image, strength: float, rng: np.random.Generator) -> Image.Image:
    """Blocks that look uniform but are not — each carries a slight gradient.

    Generators love to shade *inside* a logical pixel. A dominant-colour
    sampler should collapse that back; an averaging one smears it.
    """
    array = _rgba(image).astype(np.float64)
    height, width, _ = array.shape
    ramp_y = np.linspace(-1.0, 1.0, height)[:, None]
    ramp_x = np.linspace(-1.0, 1.0, width)[None, :]
    noise = (ramp_x * ramp_y) * 40.0 * strength
    array[:, :, :3] = np.clip(array[:, :, :3] + noise[:, :, None], 0, 255)
    return Image.fromarray(array.astype(np.uint8), mode="RGBA")


def chroma_contamination(image: Image.Image, strength: float, rng: np.random.Generator) -> Image.Image:
    """Background key bleeding into the pixels that touch it.

    "Touch it" has to include the frame border, not just the alpha edge. A
    sprite meets the key around its silhouette, but a full-bleed scene has no
    transparent pixel anywhere — and an alpha-edge-only rule degrades such an
    image not at all, which would make the static case score a perfect zero
    while testing nothing (measured: it did exactly that).
    """
    array = _rgba(image).astype(np.float64)
    opaque = array[:, :, 3] >= 128
    # Pad with "not opaque" rather than np.roll: rolling wraps the far edge in,
    # so a full-bleed image would report no border neighbours at all.
    padded = np.pad(opaque, 1, mode="constant", constant_values=False)
    neighbours = (
        padded[:-2, 1:-1] & padded[2:, 1:-1] & padded[1:-1, :-2] & padded[1:-1, 2:]
    )
    edge = opaque & ~neighbours
    key = np.array([0.0, 255.0, 0.0])
    blend = 0.5 * strength
    array[edge, :3] = array[edge, :3] * (1 - blend) + key * blend
    return Image.fromarray(np.clip(array, 0, 255).astype(np.uint8), mode="RGBA")


def boundary_bleed(image: Image.Image, strength: float, rng: np.random.Generator) -> Image.Image:
    """Colour leaking across block boundaries — averaged in linear light.

    Linear light on purpose: bleed is a physical mixing artifact, and doing it
    in gamma space would produce a darkening that no real pipeline shows.
    """
    array = _rgba(image)
    linear = srgb_to_linear(array[:, :, :3].astype(np.float64) / 255.0)
    mixed = linear.copy()
    weight = 0.35 * strength
    mixed[:, 1:] = mixed[:, 1:] * (1 - weight) + linear[:, :-1] * weight
    mixed[1:, :] = mixed[1:, :] * (1 - weight) + linear[:-1, :] * weight
    rgb = np.clip(np.rint(linear_to_srgb(mixed) * 255.0), 0, 255).astype(np.uint8)
    return Image.fromarray(np.dstack([rgb, array[:, :, 3]]), mode="RGBA")


def _min_run_lengths(occupied: np.ndarray) -> np.ndarray:
    """For each pixel, the shorter of its horizontal and vertical opaque run."""

    def runs(mask: np.ndarray) -> np.ndarray:
        height, width = mask.shape
        flat = mask.reshape(-1)
        boundary = np.zeros(flat.shape, dtype=bool)
        boundary[::width] = True
        changed = np.empty(flat.shape, dtype=bool)
        changed[0] = True
        changed[1:] = flat[1:] != flat[:-1]
        run_id = np.cumsum(changed | boundary) - 1
        return np.bincount(run_id)[run_id].reshape(height, width)

    horizontal = runs(occupied)
    vertical = runs(np.ascontiguousarray(occupied.T)).T
    return np.minimum(horizontal, vertical)


def thin_feature_loss(image: Image.Image, strength: float, rng: np.random.Generator) -> Image.Image:
    """Punch gaps into thin structures — the failure §5.6 exists to prevent.

    Thinness is measured *relative to the image's own structure*, not as a fixed
    pixel count. A ground-truth blade is one pixel wide; the same blade in the
    6x-upscaled raster a generator would produce is six, and a fixed rule calls
    that "not thin" and damages nothing — which made this case score a perfect
    recovery while testing nothing at all (measured).

    A flat scene with no thin structure is still left untouched, and that is
    correct: there is nothing there for this degradation to model.
    """
    array = _rgba(image).copy()
    opaque = array[:, :, 3] >= 128
    if not opaque.any():
        return Image.fromarray(array, mode="RGBA")
    min_run = _min_run_lengths(opaque)
    reference = float(np.median(min_run[opaque]))
    thin = opaque & (min_run <= max(1.0, reference * 0.5))
    positions = np.flatnonzero(thin.reshape(-1))
    if positions.size:
        count = max(1, int(positions.size * 0.3 * strength))
        chosen = rng.choice(positions, size=min(count, positions.size), replace=False)
        flat = array.reshape(-1, 4)
        flat[chosen] = (0, 0, 0, 0)
        array = flat.reshape(array.shape)
    return Image.fromarray(array, mode="RGBA")


DEGRADATIONS: dict[str, Degradation] = {
    item.name: item
    for item in (
        Degradation("blur", blur, "soft, painterly output instead of hard dots"),
        Degradation("subpixel_offset", subpixel_offset, "art sits between grid lines"),
        Degradation("antialiased_resize", antialiased_resize, "non-integer resize with a smoothing filter"),
        Degradation("pseudo_pixel_alias", pseudo_pixel_alias, "shading inside a logical pixel"),
        Degradation("chroma_contamination", chroma_contamination, "background key bleeding into edges"),
        Degradation("boundary_bleed", boundary_bleed, "colour leaking across block boundaries"),
        Degradation("thin_feature_loss", thin_feature_loss, "gaps punched into one-pixel structures"),
    )
}


def degrade(
    image: Image.Image,
    kinds: list[str],
    *,
    strength: float = 1.0,
    seed: int = 20260831,
) -> Image.Image:
    """Apply degradations in the given order. Unknown names are errors."""
    unknown = [kind for kind in kinds if kind not in DEGRADATIONS]
    if unknown:
        raise ValueError(f"unknown degradation(s): {unknown}; available: {sorted(DEGRADATIONS)}")
    rng = np.random.default_rng(seed)
    result = image.convert("RGBA")
    for kind in kinds:
        result = DEGRADATIONS[kind].apply(result, strength, rng)
    return result


def catalogue() -> list[dict[str, Any]]:
    return [{"name": item.name, "description": item.description} for item in DEGRADATIONS.values()]
