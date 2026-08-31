# SPDX-License-Identifier: Apache-2.0
"""Large-image grid search for scenes and tile sheets (spec §8.5).

Static Mode's grid problem is the opposite of Sprite Mode's. There is one image
rather than a row, so nothing needs to be shared across frames and phase is
free; but the image is large, so the search has to be cheap. Two things buy
that back:

* **FFT candidates** narrow which pitches are worth scoring at all (§8.2).
* **Coarse-to-fine**: integer pitch first on a decimated profile, then a
  fractional pass in a small window around the winner.

A scene has no animation to protect, so unlike Sprite Mode there is no bound on
phase — a single image may sit wherever the evidence says it sits.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np
from PIL import Image

from sprite_studio.frames.extract import axis_pitch_refine, axis_pitch_score

from studio.shared.config import LatticeSettings
from studio.shared.grid import axis_edge_profiles, profile_to_list
from studio.shared.grid.search import axis_seed, collapse_guard, scan_axis


@dataclass(frozen=True)
class SceneGrid:
    pitch: tuple[float, float]
    phase: tuple[float, float]
    confidence: tuple[float, float]
    locked: bool
    searched_candidates: tuple[float, ...]
    coarse_to_fine: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "pitch": [round(self.pitch[0], 4), round(self.pitch[1], 4)],
            "phase": [round(self.phase[0], 4), round(self.phase[1], 4)],
            "confidence": [round(self.confidence[0], 6), round(self.confidence[1], 6)],
            "locked": self.locked,
            "searched_candidates": [round(value, 4) for value in self.searched_candidates],
            "coarse_to_fine": self.coarse_to_fine,
        }


def _coarse_seeds(edges: list[int], settings: LatticeSettings, proposals: Sequence[float]) -> list[float]:
    """Integer seeds worth refining, best first: the axis's own, plus FFT proposals.

    A proposal is a real number while the coarse pass scores integers, so both
    the floor and the ceiling of each proposal get a look — an 8.0-pitch grid
    proposed as 7.97 must not be rounded out of the search.
    """
    seeds = {float(axis_seed(edges, settings.max_pitch))}
    for value in proposals:
        if value < settings.min_pitch:
            continue
        seeds.add(float(value))
        seeds.add(float(int(value)))
        if value + 1 <= settings.max_pitch:
            seeds.add(float(int(value) + 1))
    scored = [
        (axis_pitch_score(edges, int(round(seed))), seed)
        for seed in seeds
        if settings.min_pitch <= seed <= settings.max_pitch
    ]
    scored.sort(reverse=True)
    return [seed for _, seed in scored]


def detect_scene_grid(
    image: Image.Image,
    settings: LatticeSettings,
    *,
    proposals: Sequence[float] = (),
    proposals_x: Sequence[float] | None = None,
    proposals_y: Sequence[float] | None = None,
) -> SceneGrid:
    """Find the pixel lattice of one static image."""
    columns, rows = axis_edge_profiles(image)
    column_list, row_list = profile_to_list(columns), profile_to_list(rows)
    width, height = image.size
    large = width * height >= settings.large_image_pixels

    seeds_x = _coarse_seeds(column_list, settings, list(proposals_x if proposals_x is not None else proposals))
    seeds_y = _coarse_seeds(row_list, settings, list(proposals_y if proposals_y is not None else proposals))
    if settings.coarse_to_fine and large:
        # On a large image the coarse ranking is trustworthy enough to refine only
        # its top few seeds. On a small one the full seed set is cheap, so nothing
        # is dropped and no accuracy is traded for a speed we do not need.
        seeds_x, seeds_y = seeds_x[:3], seeds_y[:3]

    scan = dict(
        min_pitch=settings.min_pitch,
        max_pitch=float(settings.max_pitch),
        half_span=settings.search_half_span,
        step=settings.search_step,
    )
    fit_x = scan_axis(column_list, seeds_x, **scan)
    fit_y = scan_axis(row_list, seeds_y, **scan)
    pitch_x, pitch_y, collapsed = collapse_guard(
        fit_x.pitch, fit_y.pitch, float(columns.sum()), float(rows.sum()), min_pitch=settings.min_pitch
    )
    phase_x, phase_y = fit_x.phase, fit_y.phase
    score_x, score_y = fit_x.score, fit_y.score
    if collapsed:
        # Phase is an offset within a cell, so it only means anything against the
        # pitch it was fitted to. A borrowed pitch needs its phase re-fitted.
        score_x, phase_x = axis_pitch_refine(column_list, pitch_x)
        score_y, phase_y = axis_pitch_refine(row_list, pitch_y)

    locked = min(score_x, score_y) >= settings.confidence_floor and min(pitch_x, pitch_y) >= settings.min_pitch
    searched = tuple(sorted({*seeds_x, *seeds_y}))
    return SceneGrid(
        pitch=(pitch_x, pitch_y),
        phase=(phase_x, phase_y),
        confidence=(score_x, score_y),
        locked=locked,
        searched_candidates=searched,
        coarse_to_fine=bool(settings.coarse_to_fine and large),
    )


def block_diagnostics(image: Image.Image, grid: SceneGrid, *, blocks: int = 4) -> list[dict[str, Any]]:
    """Per-region grid agreement — where in a big scene the lattice stops holding.

    A generated 1024×1024 scene is rarely uniform: a hand-drawn-looking sky and
    a crisp tiled floor can carry different block structure. One global pitch is
    still what gets applied, but reporting which quadrants disagree with it tells
    an operator whether to crop and re-run rather than accept a soft result.
    """
    if not grid.locked:
        return []
    width, height = image.size
    step_x, step_y = max(1, width // blocks), max(1, height // blocks)
    report: list[dict[str, Any]] = []
    for row in range(blocks):
        for column in range(blocks):
            box = (column * step_x, row * step_y, min(width, (column + 1) * step_x), min(height, (row + 1) * step_y))
            if box[2] - box[0] < 8 or box[3] - box[1] < 8:
                continue
            patch = image.crop(box)
            patch_columns, patch_rows = axis_edge_profiles(patch)
            score_x, _ = axis_pitch_refine(profile_to_list(patch_columns), grid.pitch[0])
            score_y, _ = axis_pitch_refine(profile_to_list(patch_rows), grid.pitch[1])
            report.append(
                {
                    "block": [column, row],
                    "box": list(box),
                    "score": [round(float(score_x), 6), round(float(score_y), 6)],
                    "agrees": bool(min(score_x, score_y) > 0.0),
                }
            )
    return report


def crop_to_grid(image: Image.Image, grid: SceneGrid) -> tuple[Image.Image, tuple[int, int]]:
    """Trim a scene to a whole number of cells, returning the crop offset.

    Tile work needs the image to end on a cell boundary; a partial trailing cell
    is what makes a wrapped edge land half a block off.
    """
    if not grid.locked:
        return image, (0, 0)
    width, height = image.size
    offset_x = int(round(grid.phase[0] % grid.pitch[0]))
    offset_y = int(round(grid.phase[1] % grid.pitch[1]))
    cells_x = int((width - offset_x) // grid.pitch[0])
    cells_y = int((height - offset_y) // grid.pitch[1])
    if cells_x < 1 or cells_y < 1:
        return image, (0, 0)
    right = offset_x + int(round(cells_x * grid.pitch[0]))
    bottom = offset_y + int(round(cells_y * grid.pitch[1]))
    return image.crop((offset_x, offset_y, min(width, right), min(height, bottom))), (offset_x, offset_y)


def edge_density(image: Image.Image) -> float:
    """Share of sampled pixel pairs that are colour transitions — texture load."""
    columns, rows = axis_edge_profiles(image)
    width, height = image.size
    samples = max(1, (width - 1) * ((height + 1) // 2) + (height - 1) * ((width + 1) // 2))
    return float(np.sum(columns) + np.sum(rows)) / samples
