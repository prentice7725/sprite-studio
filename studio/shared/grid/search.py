# SPDX-License-Identifier: Apache-2.0
"""Pitch/phase search shared by both Refine Engines.

Sprite Mode searches an animation's pooled edge evidence; Static Mode searches
one large scene's. What they search *for* is identical, so the scan lives here
once: seed candidates, sweep a fractional window around each, keep the best
score. The scoring itself is the engine's (``axis_pitch_refine``) — this module
only decides which pitches to hand it and how to break a tie.

**The tie-break is the reason this is a module and not two copies.** The
engine's scorer measures how much edge mass lands within ±1px of a gridline, so
every pitch that keeps the same edges inside that window scores *exactly* the
same: on a 256px scene whose true pitch is 8.0, everything from 7.94 to 8.04
ties. Taking whichever tied value the loop reached first is arbitrary, and it
is not harmless — 7.94 across 32 cells accumulates two pixels of drift, which
becomes two spurious cells and a double-sampled band at the edge of the output.
Among equal scores this prefers the pitch nearest an integer, which is the
right prior for pixel art: the raster was produced by upscaling logical pixels
by a whole factor, and any fractional part is measurement noise.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from sprite_studio.frames.extract import axis_pitch_refine, axis_pitch_score, axis_pitch_seed


@dataclass(frozen=True)
class AxisFit:
    pitch: float
    phase: float
    score: float

    @property
    def integer_distance(self) -> float:
        return abs(self.pitch - round(self.pitch))


def expand_candidates(seeds: Iterable[float], *, min_pitch: float, divisors: Sequence[int] = (2, 3)) -> set[float]:
    """Seeds plus their divisors.

    An integer seed can lock onto a *multiple* of the true pitch — 33px spacing
    catches half the edges of a true 16.5px grid and still beats every integer
    that misaligns — so each seed's halves and thirds are scored alongside it.
    """
    candidates = {float(value) for value in seeds if value >= min_pitch}
    candidates |= {
        value / divisor
        for value in list(candidates)
        for divisor in divisors
        if value / divisor >= min_pitch
    }
    return candidates


def scan_axis(
    edges: Sequence[int],
    seeds: Iterable[float],
    *,
    min_pitch: float,
    max_pitch: float,
    half_span: float,
    step: float,
) -> AxisFit:
    """Best (pitch, phase, score) for one axis, ties resolved toward integers."""
    candidates = expand_candidates(seeds, min_pitch=min_pitch)
    if not candidates:
        return AxisFit(pitch=1.0, phase=0.0, score=0.0)
    edge_list = list(edges)
    span = int(round(half_span / step)) if step > 0 else 0
    best: AxisFit | None = None
    for centre in sorted(candidates):
        for offset in range(-span, span + 1):
            pitch = centre + offset * step
            if pitch < min_pitch or pitch > max_pitch:
                continue
            score, phase = axis_pitch_refine(edge_list, pitch)
            fit = AxisFit(pitch=pitch, phase=phase, score=float(score))
            if best is None or _prefer(fit, best):
                best = fit
    return best or AxisFit(pitch=1.0, phase=0.0, score=0.0)


def _prefer(candidate: AxisFit, incumbent: AxisFit) -> bool:
    if candidate.score > incumbent.score + 1e-9:
        return True
    if candidate.score < incumbent.score - 1e-9:
        return False
    return candidate.integer_distance < incumbent.integer_distance - 1e-9


def combined_seed(columns: Sequence[int], rows: Sequence[int], max_pitch: int, *, floor: float = 0.2) -> int:
    """Integer pitch that best explains both axes at once."""
    column_list, row_list = list(columns), list(rows)
    best_pitch, best_score = 1, floor
    for pitch in range(2, max_pitch + 1):
        score = axis_pitch_score(column_list, pitch) + axis_pitch_score(row_list, pitch)
        if score > best_score:
            best_pitch, best_score = pitch, score
    return best_pitch


def axis_seed(edges: Sequence[int], max_pitch: int) -> int:
    """One axis's own best integer seed (engine scorer, unchanged)."""
    return axis_pitch_seed(list(edges), max_pitch)


def collapse_guard(
    pitch_x: float,
    pitch_y: float,
    column_mass: float,
    row_mass: float,
    *,
    min_pitch: float,
    ratio_limit: float = 1.5,
) -> tuple[float, float, bool]:
    """Make a collapsed axis borrow the healthy one, and say that it happened.

    Axis pitches genuinely differ by a few percent under non-uniform rescale,
    never by half. When one axis reads more than 1.5× the other, its detection
    broke (a wall of uniform vertical bars leaves the column axis almost nothing
    to read), and the axis carrying more edge mass is the one to trust.
    """
    low, high = sorted((pitch_x, pitch_y))
    if low < min_pitch or high / low <= ratio_limit:
        return pitch_x, pitch_y, False
    if column_mass >= row_mass:
        return pitch_x, pitch_x, True
    return pitch_y, pitch_y, True
