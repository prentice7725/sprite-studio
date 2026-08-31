# SPDX-License-Identifier: MIT
"""FFT candidate proposal (spec §8.2, §5.7).

Exhaustive grid search costs `O(pitches × phases × edges)`. On a 96×96 sprite
that is free; on a 1024×1024 tile sheet with pitch up to 64 it is the slowest
thing in the pipeline, and most of the work is spent scoring pitches that the
image's own periodicity rules out in advance.

So the FFT proposes and the exact scorer disposes. A periodogram of the axis
edge profile names a handful of plausible cell sizes; the precise scorer (the
same one Sprite Mode uses, single-sourced in the engine) then checks each one
properly. **The FFT never decides the grid** — that matters, because a
periodogram happily reports a strong peak for a texture's repeat period, which
is not the pixel lattice at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np
from PIL import Image

from studio.shared.config import FftSettings, LatticeSettings
from studio.shared.grid import axis_edge_profiles


@dataclass(frozen=True)
class CellSizeCandidate:
    period: float
    power: float
    axis: str

    def to_dict(self) -> dict[str, Any]:
        return {"period": round(self.period, 4), "power": round(self.power, 6), "axis": self.axis}


def _periodogram_candidates(
    profile: np.ndarray,
    *,
    axis: str,
    min_pitch: float,
    max_pitch: float,
    count: int,
    min_prominence: float,
) -> list[CellSizeCandidate]:
    values = np.asarray(profile, dtype=np.float64)
    length = values.size
    if length < 8 or not np.any(values):
        return []
    # Remove the DC term before transforming: the mean edge density is a large
    # constant that otherwise dominates the spectrum and buries every real peak.
    centred = values - values.mean()
    if not np.any(centred):
        return []
    spectrum = np.abs(np.fft.rfft(centred)) ** 2
    frequencies = np.arange(spectrum.size, dtype=np.float64)
    with np.errstate(divide="ignore"):
        periods = np.where(frequencies > 0, length / np.maximum(frequencies, 1e-9), np.inf)
    usable = (periods >= min_pitch) & (periods <= max_pitch) & (frequencies > 0)
    if not np.any(usable):
        return []
    power = spectrum / spectrum[usable].max()
    # Local maxima only. Every bin adjacent to a strong peak is also large, and
    # taking the top-k bins outright would spend the whole candidate budget on
    # one peak's shoulders.
    peaks: list[tuple[float, float]] = []
    for index in np.flatnonzero(usable):
        left = spectrum[index - 1] if index > 0 else 0.0
        right = spectrum[index + 1] if index + 1 < spectrum.size else 0.0
        if spectrum[index] >= left and spectrum[index] >= right and power[index] >= min_prominence:
            peaks.append((float(periods[index]), float(power[index])))
    peaks.sort(key=lambda item: item[1], reverse=True)
    return [CellSizeCandidate(period=period, power=value, axis=axis) for period, value in peaks[:count]]


def propose_cell_sizes(
    image: Image.Image,
    fft: FftSettings,
    lattice: LatticeSettings,
) -> list[CellSizeCandidate]:
    """Plausible cell sizes from the image's own periodicity, both axes."""
    if not fft.candidate_search:
        return []
    columns, rows = axis_edge_profiles(image)
    candidates = _periodogram_candidates(
        columns, axis="x", min_pitch=lattice.min_pitch, max_pitch=float(lattice.max_pitch),
        count=fft.candidates, min_prominence=fft.min_prominence,
    )
    candidates += _periodogram_candidates(
        rows, axis="y", min_pitch=lattice.min_pitch, max_pitch=float(lattice.max_pitch),
        count=fft.candidates, min_prominence=fft.min_prominence,
    )
    return candidates


def candidate_periods(candidates: Sequence[CellSizeCandidate], *, axis: str | None = None) -> list[float]:
    """Bare period values for the exact scorer to seed from."""
    selected = [item for item in candidates if axis is None or item.axis == axis]
    ordered = sorted(selected, key=lambda item: item.power, reverse=True)
    seen: list[float] = []
    for item in ordered:
        if all(abs(item.period - value) > 0.25 for value in seen):
            seen.append(item.period)
    return seen
