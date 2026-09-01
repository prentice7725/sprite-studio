# SPDX-License-Identifier: Apache-2.0
"""Frame-set sampling against one locked lattice (spec §5.1).

Everything the Sprite Refine Engine knows about a state arrives here at once:
the locked pitch, each frame's bounded phase, each frame's thin-feature
protection. The rule this module enforces is the one that makes an animation
hold together — **every frame lands on the same logical canvas**. Cut lines are
derived once from the shared lattice and then *shifted* by each frame's bounded
phase offset, so the cell count is identical across the row by construction
rather than by luck.

The alternative (rebuilding cut lines per frame from its own phase) yields
43 cells in one frame and 44 in the next, and no downstream stage can line
those up again.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np
from PIL import Image

from studio.shared.config import RefineSettings
from studio.shared.grid import SampleReport, grid_edges, snap_to_lattice

from .lattice import SharedLattice
from .phase import FramePhase
from .thin_feature import ThinFeatureMask, thin_feature_mask, with_temporal_support


@dataclass(frozen=True)
class SampledFrame:
    index: int
    logical: Image.Image
    phase: FramePhase
    protection: ThinFeatureMask
    sample: SampleReport

    def to_dict(self) -> dict[str, Any]:
        return {
            "frame": self.index,
            "phase": self.phase.to_dict(),
            "thin_feature": self.protection.to_dict(),
            "sample": self.sample.to_dict(),
        }


def shift_edges(edges: Sequence[int], delta: float, extent: int) -> list[int]:
    """Move interior cut lines by ``delta`` pixels, keeping the cell count fixed.

    The image borders stay pinned at 0 and ``extent``; the first and last cells
    absorb the shift. Because phase correction is bounded to a fraction of a
    cell, that absorption is bounded too — the edge cells breathe by less than
    one cell and no cell is ever created or destroyed.
    """
    offset = int(round(delta))
    if offset == 0:
        return list(edges)
    moved = [0]
    for value in edges[1:-1]:
        candidate = min(max(value + offset, moved[-1] + 1), extent - 1)
        if candidate > moved[-1]:
            moved.append(candidate)
    moved.append(extent)
    if len(moved) != len(edges):
        # Squeezing at a border would change the cell count and break the shared
        # canvas. Keep the unshifted lines rather than deliver a different grid.
        return list(edges)
    return moved


def sample_frames(
    frames: Sequence[Image.Image],
    lattice: SharedLattice,
    phases: Sequence[FramePhase],
    settings: RefineSettings,
) -> list[SampledFrame]:
    """Snap every frame of a state onto the shared lattice."""
    if len(frames) != len(phases):
        raise ValueError("one phase per frame is required")
    if not frames:
        raise ValueError("no frames to sample")
    width, height = frames[0].size
    if any(frame.size != (width, height) for frame in frames):
        raise ValueError("all frames must share one cell size before refine")

    if not lattice.locked:
        # No trustworthy grid: sample at 1:1 so the stage stays a no-op on
        # geometry instead of snapping the row to a grid nothing supports.
        base_x = list(range(width + 1))
        base_y = list(range(height + 1))
    else:
        base_x = grid_edges(width, lattice.pitch[0], lattice.phase[0])
        base_y = grid_edges(height, lattice.pitch[1], lattice.phase[1])

    raw_masks = [
        thin_feature_mask(frame, settings.thin_feature, pitch=lattice.pitch)
        for frame in frames
    ]
    protections = with_temporal_support(raw_masks, settings.thin_feature)

    sampled: list[SampledFrame] = []
    for index, frame in enumerate(frames):
        phase = phases[index]
        x_edges = shift_edges(base_x, phase.offset[0], width) if lattice.locked else base_x
        y_edges = shift_edges(base_y, phase.offset[1], height) if lattice.locked else base_y
        protection = protections[index]
        logical, report = snap_to_lattice(
            frame,
            x_edges,
            y_edges,
            weighting=settings.weighting,
            color=settings.color,
            protect_mask=protection.mask if settings.thin_feature.enabled else None,
            coverage_relief=settings.thin_feature.coverage_relief if settings.thin_feature.enabled else 0.0,
        )
        sampled.append(SampledFrame(index=index, logical=logical, phase=phase, protection=protection, sample=report))
    sizes = {frame.logical.size for frame in sampled}
    if len(sizes) != 1:
        raise ValueError(f"shared lattice produced mixed logical sizes: {sorted(sizes)}")
    return sampled


def residual_thin_features(sampled: Sequence[SampledFrame]) -> list[dict[str, Any]]:
    """Thin features that protection could not save — the handoff to Repair (spec §5.1).

    Refine reports what it lost instead of trying harder. A cell that was
    protected in the source and still came out empty is exactly the bounded,
    local defect the Repair layer is built for, and naming it here is what
    keeps "refine kept it" and "repair rebuilt it" separable in the record.
    """
    residues: list[dict[str, Any]] = []
    for frame in sampled:
        lost = frame.protection.protected_pixels - frame.sample.rescued_cells
        if frame.sample.lost_cells:
            for x, y in frame.sample.lost_cells:
                residues.append(
                    {
                        "frame": frame.index,
                        "type": "thin_feature_at_risk",
                        "logical_region": {"x": x, "y": y, "w": 1, "h": 1},
                        "pixels": [[x, y]],
                        "evidence": {
                            "protected_pixels": frame.protection.protected_pixels,
                            "rescued_cells": frame.sample.rescued_cells,
                        },
                        "hint": "repair layer should verify thin-feature continuity on this cell",
                    }
                )
        elif frame.protection.protected_pixels and frame.sample.rescued_cells == 0 and lost > 0:
            residues.append(
                {
                    "frame": frame.index,
                    "type": "thin_feature_at_risk",
                    "logical_region": {"x": 0, "y": 0, "w": frame.logical.width, "h": frame.logical.height},
                    "pixels": [],
                    "evidence": {
                        "protected_pixels": frame.protection.protected_pixels,
                        "rescued_cells": frame.sample.rescued_cells,
                    },
                    "hint": "repair layer should verify thin-feature continuity on this frame",
                }
            )
    return residues


def logical_bounds(sampled: Sequence[SampledFrame]) -> tuple[int, int, int, int]:
    """Union content bbox across the row — the shared crop the whole state uses."""
    boxes = [frame.logical.getchannel("A").getbbox() for frame in sampled]
    present = [box for box in boxes if box is not None]
    if not present:
        raise ValueError("every refined frame is empty")
    return (
        min(box[0] for box in present),
        min(box[1] for box in present),
        max(box[2] for box in present),
        max(box[3] for box in present),
    )


def content_heights(sampled: Sequence[SampledFrame]) -> list[int]:
    heights: list[int] = []
    for frame in sampled:
        box = frame.logical.getchannel("A").getbbox()
        heights.append(0 if box is None else box[3] - box[1])
    return heights


def as_arrays(sampled: Sequence[SampledFrame]) -> list[np.ndarray]:
    return [np.asarray(frame.logical, dtype=np.uint8) for frame in sampled]
