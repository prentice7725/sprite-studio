# SPDX-License-Identifier: Apache-2.0
"""Thin-feature protection during refine (spec §5.6).

A sword tip, a spear shaft, a bowstring, a plume, a horn, a tail — these are
one or two logical cells wide. They are also what makes a 48×48 silhouette
readable, and they are the first thing a coverage threshold throws away: a
one-cell blade that lands slightly off the lattice covers 40% of its cells and
loses every one of them, and the character comes out holding a stump.

Protection here is deliberately weak on purpose. It marks source pixels that
belong to a thin structure so the sampler can accept them on *less* coverage
(``thin_feature.coverage_relief``). It never paints a pixel, never bridges a
gap, never moves anything. What refine still fails to keep is handed to the
Repair layer as residue (spec §5.1) — the split exists so that "refine kept
it" and "repair invented it" stay distinguishable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np
from PIL import Image

from studio.shared.config import ThinFeatureSettings


ALPHA_THRESHOLD = 128


@dataclass(frozen=True)
class ThinFeatureMask:
    mask: np.ndarray
    thickness_px: int
    protected_pixels: int
    temporal_support: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "thickness_px": self.thickness_px,
            "protected_pixels": self.protected_pixels,
            "temporal_support": self.temporal_support,
        }


def _run_lengths(occupied: np.ndarray) -> np.ndarray:
    """Length of the contiguous horizontal run each pixel belongs to.

    Row-major flattening with an explicit break at every row start, so runs
    cannot bleed from the end of one row into the beginning of the next.
    """
    height, width = occupied.shape
    if width == 0 or height == 0:
        return np.zeros_like(occupied, dtype=np.int64)
    flat = occupied.reshape(-1)
    boundary = np.zeros(flat.shape, dtype=bool)
    boundary[::width] = True
    changed = np.empty(flat.shape, dtype=bool)
    changed[0] = True
    changed[1:] = flat[1:] != flat[:-1]
    run_id = np.cumsum(changed | boundary) - 1
    lengths = np.bincount(run_id)
    return lengths[run_id].reshape(height, width)


def thin_feature_mask(
    image: Image.Image,
    settings: ThinFeatureSettings,
    *,
    pitch: tuple[float, float],
    alpha_threshold: int = ALPHA_THRESHOLD,
) -> np.ndarray:
    """Source pixels belonging to a structure at most ``max_thickness`` cells thick."""
    alpha = np.asarray(image.convert("RGBA"), dtype=np.uint8)[:, :, 3]
    occupied = alpha >= alpha_threshold
    if not settings.enabled or not occupied.any():
        return np.zeros_like(occupied, dtype=bool)
    # Thickness is declared in logical cells but measured in source pixels, so it
    # scales with the lattice: two cells of a 3px pitch and two cells of a 20px
    # pitch are both "thin", and a fixed pixel threshold would call one of them
    # the whole character.
    limit_x = max(1, int(round(settings.max_thickness * max(1.0, pitch[0]))))
    limit_y = max(1, int(round(settings.max_thickness * max(1.0, pitch[1]))))
    horizontal = _run_lengths(occupied)
    vertical = _run_lengths(np.ascontiguousarray(occupied.T)).T
    return occupied & ((horizontal <= limit_x) | (vertical <= limit_y))


def _dilate(mask: np.ndarray, radius: int) -> np.ndarray:
    if radius <= 0:
        return mask
    grown = mask.copy()
    for _ in range(radius):
        shifted = grown.copy()
        shifted[1:, :] |= grown[:-1, :]
        shifted[:-1, :] |= grown[1:, :]
        shifted[:, 1:] |= grown[:, :-1]
        shifted[:, :-1] |= grown[:, 1:]
        grown = shifted
    return grown


def with_temporal_support(
    masks: Sequence[np.ndarray],
    settings: ThinFeatureSettings,
    *,
    radius: int = 1,
) -> list[ThinFeatureMask]:
    """Let neighbouring frames vouch for a thin feature this frame nearly lost.

    If frames i−1 and i+1 both show a thin structure at a location and frame i
    shows opaque pixels there too — just not thin enough on its own to qualify —
    the neighbours' evidence extends protection to frame i. Both neighbours must
    agree: one neighbour is a coincidence, and a feature that genuinely leaves
    the frame (a swung blade) should be allowed to leave.

    Borrowed protection still cannot create anything — the sampler intersects
    every protect mask with the frame's own opaque pixels, so a neighbour can
    only rescue evidence this frame already has.
    """
    count = len(masks)
    results: list[ThinFeatureMask] = []
    for index, mask in enumerate(masks):
        support = np.zeros_like(mask, dtype=bool)
        if settings.enabled and settings.temporal_evidence and 0 < index < count - 1:
            support = _dilate(masks[index - 1], radius) & _dilate(masks[index + 1], radius) & ~mask
        combined = mask | support
        results.append(
            ThinFeatureMask(
                mask=combined,
                thickness_px=int(settings.max_thickness),
                protected_pixels=int(np.count_nonzero(combined)),
                temporal_support=int(np.count_nonzero(support)),
            )
        )
    return results
