# SPDX-License-Identifier: MIT
"""Small-cell continuous weighting (spec §5.4).

The predecessor used a hard core margin: sample only the inner part of a cell,
discard the boundary band. That is fine at 16px cells and destructive at 5px
ones, where the margin rounds to zero and the cell has no interior left — which
is exactly where thin features live (a sword edge, a plume tip, a one-cell
outline). Their evidence sat in the band that got thrown away, so they thinned
or vanished.

Continuous weighting replaces the cut with a falloff: the centre still
dominates, the boundary still counts for little, but nothing is ever multiplied
by zero. Cells of any size keep a usable sample.

The curve is data (``weighting.anchors``), piecewise-linear through the spec's
anchor points: centre 1.0, inner 0.7, near-boundary 0.3, edge fringe 0.1.
"""

from __future__ import annotations

from typing import Sequence

import numpy as np


def weight_curve(radius: np.ndarray, anchors: Sequence[tuple[float, float]]) -> np.ndarray:
    """Interpolate the falloff curve at normalised radii in [0, 1]."""
    positions = np.asarray([anchor[0] for anchor in anchors], dtype=np.float64)
    values = np.asarray([anchor[1] for anchor in anchors], dtype=np.float64)
    return np.interp(np.clip(np.asarray(radius, dtype=np.float64), 0.0, 1.0), positions, values)


def cell_weights(
    start: int,
    stop: int,
    anchors: Sequence[tuple[float, float]],
) -> np.ndarray:
    """Per-pixel weights along one axis of one cell spanning ``[start, stop)``.

    Radius is measured from the cell centre in units of the cell half-width, so
    a 3px cell and a 30px cell get the same shaped curve — the reason a small
    cell no longer degenerates.
    """
    length = stop - start
    if length <= 0:
        raise ValueError("cell span must be positive")
    if length == 1:
        return np.ones(1, dtype=np.float64)
    centres = np.arange(length, dtype=np.float64) + 0.5
    half = length / 2.0
    radius = np.abs(centres - half) / half
    return weight_curve(radius, anchors)


def cell_weight_grid(
    x_start: int, x_stop: int, y_start: int, y_stop: int,
    anchors: Sequence[tuple[float, float]],
) -> np.ndarray:
    """2-D separable weight patch for one cell — outer product of the axis curves."""
    return np.outer(cell_weights(y_start, y_stop, anchors), cell_weights(x_start, x_stop, anchors))
