# SPDX-License-Identifier: Apache-2.0
"""Axis edge profiles — the grid evidence both Refine Engines read.

The *definition* of an edge lives in ``sprite_studio.frames.extract`` (public seam
``axis_edge_histograms``): a colour/alpha transition whose summed per-channel
delta exceeds 96, counted on every other scanline. This module is that same
definition expressed in NumPy, because Studio needs it at two scales the engine
helper was never sized for — a whole animation's frames summed into one shared
lattice (spec §5.2) and 1024×1024 scenes (spec §8.5).

``tests/shared/test_edge_profiles.py`` locks the two against each other on
fixtures. If they ever disagree, this file is wrong, not the engine: Studio may
choose a grid the engine then has to snap to.
"""

from __future__ import annotations

from typing import Iterable, Sequence

import numpy as np
from PIL import Image


EDGE_DELTA_THRESHOLD = 96
SCANLINE_STRIDE = 2


def axis_edge_profiles(image: Image.Image) -> tuple[np.ndarray, np.ndarray]:
    """(column edge counts indexed by x, row edge counts indexed by y)."""
    array = np.asarray(image.convert("RGBA"), dtype=np.int16)
    height, width, _ = array.shape
    col_edges = np.zeros(width, dtype=np.int64)
    row_edges = np.zeros(height, dtype=np.int64)
    if width > 1:
        sampled = array[::SCANLINE_STRIDE]
        delta = np.abs(sampled[:, 1:, :] - sampled[:, :-1, :]).sum(axis=2)
        col_edges[1:] = (delta > EDGE_DELTA_THRESHOLD).sum(axis=0)
    if height > 1:
        sampled = array[:, ::SCANLINE_STRIDE, :]
        delta = np.abs(sampled[1:, :, :] - sampled[:-1, :, :]).sum(axis=2)
        row_edges[1:] = (delta > EDGE_DELTA_THRESHOLD).sum(axis=1)
    return col_edges, row_edges


def accumulate_edge_profiles(images: Iterable[Image.Image]) -> tuple[np.ndarray, np.ndarray]:
    """Sum edge profiles across frames — the shared-lattice evidence pool.

    Summing before scoring, rather than scoring each frame and averaging, is
    the point of a shared lattice: a frame where the character barely moves
    contributes few edges and should not get an equal vote on cell pitch.
    """
    columns: np.ndarray | None = None
    rows: np.ndarray | None = None
    for image in images:
        col_edges, row_edges = axis_edge_profiles(image)
        if columns is None:
            columns, rows = col_edges.copy(), row_edges.copy()
            continue
        if col_edges.shape != columns.shape or row_edges.shape != rows.shape:
            raise ValueError("shared lattice needs frames of one size; extract them to the same cell first")
        columns += col_edges
        rows += row_edges
    if columns is None or rows is None:
        raise ValueError("no frames given")
    return columns, rows


def grid_edges(extent: int, pitch: float, phase: float) -> list[int]:
    """Integer cut lines for a fractional pitch/phase — cells are whole pixels.

    Measurement is fractional (an AI block is 17.24px wide, never 17); the cuts
    have to be integers because pixels are. Rounding each line independently
    keeps the fractional part from accumulating across the width.
    """
    if pitch < 1.0:
        raise ValueError("pitch must be at least 1.0")
    offset = float(phase) % pitch
    start = offset - pitch if offset > 0 else offset
    edges: list[int] = []
    position = start
    while position < extent + pitch:
        value = int(round(position))
        if 0 <= value <= extent and (not edges or value > edges[-1]):
            edges.append(value)
        position += pitch
    if not edges or edges[0] != 0:
        edges.insert(0, 0)
    if edges[-1] != extent:
        edges.append(extent)
    return [value for index, value in enumerate(edges) if index == 0 or value > edges[index - 1]]


def cell_count(extent: int, pitch: float, phase: float) -> int:
    return max(1, len(grid_edges(extent, pitch, phase)) - 1)


def profile_to_list(profile: Sequence[int] | np.ndarray) -> list[int]:
    """Engine scorers take plain lists; keep the conversion in one place."""
    return [int(value) for value in profile]
