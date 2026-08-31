# SPDX-License-Identifier: Apache-2.0
"""Animation Shared Lattice — one cell pitch for a whole state (spec §5.2).

Per-frame grid detection is correct for a single image and wrong for an
animation: cell pitch estimated independently per frame lands on 6.0 in one
frame and 6.3 in the next, and the dots visibly boil across the row even though
every frame is individually plausible. So the pitch is estimated **once** from
the frames' summed edge evidence and locked for the state (or the whole
character, per ``lattice.scope``); only phase is allowed to move per frame, and
only within bounds — see ``phase.py``.

Neither the edge definition nor the pitch scorer is re-derived here. Both come
from the engine's public seam via Shared Core; this module only changes *what
they are pointed at* — an aggregate over frames instead of one image.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from PIL import Image

from sprite_studio.frames.extract import axis_pitch_refine

from studio.shared.config import LatticeSettings
from studio.shared.grid import accumulate_edge_profiles, profile_to_list
from studio.shared.grid.search import axis_seed, collapse_guard, combined_seed, scan_axis


@dataclass(frozen=True)
class SharedLattice:
    """The locked grid for a frame set. ``locked=False`` means: do not snap."""

    pitch: tuple[float, float]
    phase: tuple[float, float]
    confidence: tuple[float, float]
    scope: str
    frame_count: int
    locked: bool
    candidates: tuple[float, ...] = ()
    axis_collapsed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "pitch": [round(self.pitch[0], 4), round(self.pitch[1], 4)],
            "phase": [round(self.phase[0], 4), round(self.phase[1], 4)],
            "confidence": [round(self.confidence[0], 6), round(self.confidence[1], 6)],
            "scope": self.scope,
            "frame_count": self.frame_count,
            "locked": self.locked,
            "candidates": [round(value, 4) for value in self.candidates],
            "axis_collapsed": self.axis_collapsed,
        }


def estimate_shared_lattice(
    frames: Sequence[Image.Image],
    settings: LatticeSettings,
    *,
    extra_candidates: Sequence[float] = (),
) -> SharedLattice:
    """Estimate one lattice from every frame of a state.

    ``extra_candidates`` lets a caller inject FFT-proposed cell sizes (spec
    §5.7) as additional seeds. They are proposals only — the scorer still
    decides, so a bad FFT peak costs search time and never picks the grid.
    """
    if not frames:
        raise ValueError("shared lattice needs at least one frame")
    columns, rows = accumulate_edge_profiles(frames)
    column_list, row_list = profile_to_list(columns), profile_to_list(rows)
    combined = combined_seed(column_list, row_list, settings.max_pitch, floor=settings.confidence_floor)
    injected = {float(value) for value in extra_candidates if value >= settings.min_pitch}
    if combined <= 1 and not injected:
        # No grid worth trusting. Report it instead of snapping to a grid the
        # evidence does not support — a wrong lattice is worse than none.
        return SharedLattice(
            pitch=(1.0, 1.0), phase=(0.0, 0.0), confidence=(0.0, 0.0),
            scope=settings.scope, frame_count=len(frames), locked=False,
        )

    scan = dict(
        min_pitch=settings.min_pitch,
        max_pitch=float(settings.max_pitch),
        half_span=settings.search_half_span,
        step=settings.search_step,
    )
    fit_x = scan_axis(column_list, {float(axis_seed(column_list, settings.max_pitch)), float(combined)} | injected, **scan)
    fit_y = scan_axis(row_list, {float(axis_seed(row_list, settings.max_pitch)), float(combined)} | injected, **scan)

    pitch_x, pitch_y, collapsed = collapse_guard(
        fit_x.pitch, fit_y.pitch, float(columns.sum()), float(rows.sum()), min_pitch=settings.min_pitch
    )
    phase_x, phase_y = fit_x.phase, fit_y.phase
    if collapsed:
        # A borrowed pitch invalidates the phase measured for the pitch it
        # replaced: phase is an offset *within a cell*, so it is only meaningful
        # against the pitch it was fitted to. Re-fit both axes at the pitch that
        # actually won, or the surviving axis lands the grid at the wrong offset.
        phase_x = axis_pitch_refine(column_list, pitch_x)[1]
        phase_y = axis_pitch_refine(row_list, pitch_y)[1]
    locked = (
        min(fit_x.score, fit_y.score) >= settings.confidence_floor
        and min(pitch_x, pitch_y) >= settings.min_pitch
    )
    return SharedLattice(
        pitch=(pitch_x, pitch_y),
        phase=(phase_x, phase_y),
        confidence=(fit_x.score, fit_y.score),
        scope=settings.scope,
        frame_count=len(frames),
        locked=locked,
        candidates=tuple(sorted(injected)),
        axis_collapsed=collapsed,
    )
