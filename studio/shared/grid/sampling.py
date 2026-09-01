# SPDX-License-Identifier: Apache-2.0
"""Oklab-consistent, continuously weighted cell sampling (spec §5.4, §5.5, §8.3).

This is the one place a lattice becomes logical pixels. Both modes call it, so
both get the same answers to the same two questions:

* **Is this cell filled?** Weighted opaque coverage against a threshold — not a
  raw pixel count, so a cell whose only opaque pixels sit on its boundary does
  not read as solid, and a thin feature that owns the cell centre does.
* **What colour is this cell?** The weighted mean of the dominant cluster of a
  2-means split performed *in Oklab*. The engine's per-block splitter is the
  same idea in RGB; Oklab is what makes the answer agree with the palette build
  and the continuity tests that read this output downstream.

Vectorised over the whole image: cells are addressed by label, so a 1024×1024
scene at pitch 4 (65k cells) costs a handful of ``bincount`` passes rather than
65k Python iterations.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np
from PIL import Image

from studio.shared.color.oklab import oklab_to_rgb, rgb_to_oklab
from studio.shared.config import ColorSettings, WeightingSettings

from .weighting import cell_weights


ALPHA_THRESHOLD = 128


@dataclass(frozen=True)
class SampleReport:
    logical_size: tuple[int, int]
    filled_cells: int
    protected_cells: int
    rescued_cells: int
    mean_coverage: float
    lost_cells: tuple[tuple[int, int], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "logical_size": [self.logical_size[0], self.logical_size[1]],
            "filled_cells": self.filled_cells,
            "protected_cells": self.protected_cells,
            "rescued_cells": self.rescued_cells,
            "mean_coverage": round(self.mean_coverage, 6),
            "lost_cells": [list(cell) for cell in self.lost_cells],
        }


def _axis_weights(edges: Sequence[int], anchors: Sequence[tuple[float, float]]) -> tuple[np.ndarray, np.ndarray]:
    """Per-pixel weights and per-pixel cell index for one axis."""
    weights: list[np.ndarray] = []
    labels: list[np.ndarray] = []
    for index in range(len(edges) - 1):
        start, stop = edges[index], edges[index + 1]
        weights.append(cell_weights(start, stop, anchors))
        labels.append(np.full(stop - start, index, dtype=np.int64))
    return np.concatenate(weights), np.concatenate(labels)


def _cluster_split(
    lab: np.ndarray,
    weights: np.ndarray,
    labels: np.ndarray,
    cells: int,
    iterations: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Weighted 2-means per cell, in Oklab. Returns (centroids, cluster weights).

    Seeded by each cell's weighted mean lightness rather than by its min/max
    luma pixels: the split a 2-means converges to is a plane, and starting from
    the cell's own centre of mass reaches it in fewer passes without a
    per-cell gather. Deterministic — no RNG anywhere in the refine path.
    """
    lightness = lab[:, 0]
    cell_weight = np.bincount(labels, weights=weights, minlength=cells)
    safe = np.where(cell_weight > 0, cell_weight, 1.0)
    mean_lightness = np.bincount(labels, weights=weights * lightness, minlength=cells) / safe
    assign = (lightness > mean_lightness[labels]).astype(np.int64)

    centroids = np.zeros((cells, 2, 3), dtype=np.float64)
    cluster_weight = np.zeros((cells, 2), dtype=np.float64)
    for _ in range(max(1, iterations)):
        slot = labels * 2 + assign
        cluster_weight = np.bincount(slot, weights=weights, minlength=cells * 2).reshape(cells, 2)
        divisor = np.where(cluster_weight > 0, cluster_weight, 1.0)
        for channel in range(3):
            total = np.bincount(slot, weights=weights * lab[:, channel], minlength=cells * 2)
            centroids[:, :, channel] = total.reshape(cells, 2) / divisor
        # An empty cluster keeps the other one's colour so distances stay finite;
        # it holds zero weight, so it can never win the dominance vote below.
        empty = cluster_weight <= 0
        if empty.any():
            centroids[empty[:, 0], 0] = centroids[empty[:, 0], 1]
            centroids[empty[:, 1], 1] = centroids[empty[:, 1], 0]
        near = centroids[labels]
        distance = np.sum((lab[:, None, :] - near) ** 2, axis=2)
        updated = np.argmin(distance, axis=1)
        if np.array_equal(updated, assign):
            break
        assign = updated
    return centroids, cluster_weight


def snap_to_lattice(
    image: Image.Image,
    x_edges: Sequence[int],
    y_edges: Sequence[int],
    *,
    weighting: WeightingSettings,
    color: ColorSettings,
    protect_mask: np.ndarray | None = None,
    coverage_relief: float = 0.0,
    alpha_threshold: int = ALPHA_THRESHOLD,
) -> tuple[Image.Image, SampleReport]:
    """Downscale ``image`` onto the given cut lines. One logical pixel per cell."""
    if color.metric != "oklab":
        raise ValueError(f"only the oklab colour metric is supported (got {color.metric!r})")
    source = np.asarray(image.convert("RGBA"), dtype=np.uint8)
    height, width, _ = source.shape
    if x_edges[0] != 0 or x_edges[-1] != width or y_edges[0] != 0 or y_edges[-1] != height:
        raise ValueError("cut lines must span the image exactly")
    columns, rows = len(x_edges) - 1, len(y_edges) - 1
    cells = columns * rows

    weight_x, label_x = _axis_weights(x_edges, weighting.anchors)
    weight_y, label_y = _axis_weights(y_edges, weighting.anchors)
    weights = (weight_y[:, None] * weight_x[None, :]).reshape(-1)
    labels = (label_y[:, None] * columns + label_x[None, :]).reshape(-1)

    flat = source.reshape(-1, 4)
    opaque = flat[:, 3] >= alpha_threshold
    opaque_weights = weights * opaque

    total_weight = np.bincount(labels, weights=weights, minlength=cells)
    filled_weight = np.bincount(labels, weights=opaque_weights, minlength=cells)
    coverage = filled_weight / np.where(total_weight > 0, total_weight, 1.0)

    threshold = np.full(cells, float(weighting.coverage_threshold), dtype=np.float64)
    protected = np.zeros(cells, dtype=bool)
    if protect_mask is not None and coverage_relief > 0.0:
        mask = np.asarray(protect_mask, dtype=bool).reshape(-1) & opaque
        protected = np.bincount(labels, weights=mask.astype(np.float64), minlength=cells) > 0
        # A protected cell is allowed to survive on less coverage. It is a
        # relaxation, never a free pass: a cell holding no opaque pixel at all
        # still cannot be filled.
        threshold[protected] = max(0.0, float(weighting.coverage_threshold) - float(coverage_relief))

    keep = (coverage >= threshold) & (filled_weight > 0)
    rescued = int(np.count_nonzero(keep & protected & (coverage < float(weighting.coverage_threshold))))

    lab = rgb_to_oklab(flat[opaque][:, :3])
    centroids, cluster_weight = _cluster_split(
        lab, opaque_weights[opaque], labels[opaque], cells, color.cluster_iterations
    )

    dominant = np.argmax(cluster_weight, axis=1)
    if color.detail_bias:
        # Dark minority detail (eyes, outlines) loses a pure majority vote even
        # though it carries the readability of the sprite. When the two clusters
        # are far apart in lightness and the darker one holds a real share of the
        # cell, the darker one takes the cell.
        darker = np.argmin(centroids[:, :, 0], axis=1)
        total = cluster_weight.sum(axis=1)
        share = np.divide(
            cluster_weight[np.arange(cells), darker], total,
            out=np.zeros(cells), where=total > 0,
        )
        gap = np.abs(centroids[:, 0, 0] - centroids[:, 1, 0])
        # The minority must also be genuinely dark. Without this, two mid-tones a
        # long way apart in lightness let a *bright* minority hijack the cell,
        # which is the opposite of the outline/eye preservation this rule is for.
        darkness = centroids[np.arange(cells), darker, 0]
        take_dark = (
            (share >= color.detail_bias_share)
            & (gap >= color.detail_bias_lightness_gap)
            & (darkness <= color.detail_bias_max_lightness)
        )
        dominant = np.where(take_dark, darker, dominant)

    representative = centroids[np.arange(cells), dominant]
    rgb = oklab_to_rgb(representative)
    output = np.zeros((cells, 4), dtype=np.uint8)
    output[keep, :3] = rgb[keep]
    output[keep, 3] = 255
    logical = Image.fromarray(output.reshape(rows, columns, 4), mode="RGBA")
    lost_mask = protected & (~keep)
    lost_cells = tuple((int(idx % columns), int(idx // columns)) for idx in np.flatnonzero(lost_mask))

    report = SampleReport(
        logical_size=(columns, rows),
        filled_cells=int(np.count_nonzero(keep)),
        protected_cells=int(np.count_nonzero(protected)),
        rescued_cells=rescued,
        mean_coverage=float(coverage[filled_weight > 0].mean()) if np.any(filled_weight > 0) else 0.0,
        lost_cells=lost_cells,
    )
    return logical, report
