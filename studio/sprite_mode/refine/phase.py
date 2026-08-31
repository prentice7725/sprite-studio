# SPDX-License-Identifier: MIT
"""Bounded Phase Correction — per-frame alignment inside a safety fence (spec §5.3).

The lattice locks pitch for the state; each frame still needs its own phase,
because the generator does not place the character on the same subpixel every
frame. What a frame must *not* get is freedom: an unbounded per-frame phase
search is a spatial warp with extra steps — it moves the silhouette, and across
a row that reads as the character sliding and rubber-banding.

So the correction is a search over a window around the shared phase, at most
``phase.tolerance`` of a cell wide, and the result is reported (not silently
clamped) when a frame wanted to leave that window.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from PIL import Image

from sprite_studio.frames.extract import axis_pitch_refine

from studio.shared.config import PhaseSettings
from studio.shared.grid import axis_edge_profiles, profile_to_list


@dataclass(frozen=True)
class FramePhase:
    frame: int
    offset: tuple[float, float]
    applied: tuple[float, float]
    clamped: bool
    score: tuple[float, float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "frame": self.frame,
            "offset": [round(self.offset[0], 4), round(self.offset[1], 4)],
            "phase": [round(self.applied[0], 4), round(self.applied[1], 4)],
            "clamped": self.clamped,
            "score": [round(self.score[0], 6), round(self.score[1], 6)],
        }


def _wrap_delta(value: float, pitch: float) -> float:
    """Shortest signed distance between two phases on a pitch-periodic circle.

    Phase 0.1 and phase 5.9 on a 6.0 pitch are 0.2 apart, not 5.8. Measuring
    that linearly is how a frame that is already aligned gets reported as
    maximally clamped.
    """
    half = pitch / 2.0
    delta = (value + half) % pitch - half
    return delta


def _search_axis(
    edges: list[int],
    pitch: float,
    shared_phase: float,
    settings: PhaseSettings,
) -> tuple[float, float, bool]:
    """Best phase within tolerance of the shared phase, plus whether it hit the fence."""
    if pitch < 1.0:
        return shared_phase, 0.0, False
    window = max(0.0, float(settings.tolerance)) * pitch
    if window <= 0.0:
        score, _ = axis_pitch_refine(edges, pitch)
        return shared_phase, score, False
    free_score, free_phase = axis_pitch_refine(edges, pitch)
    delta = _wrap_delta(free_phase - shared_phase, pitch)
    if abs(delta) <= window + 1e-9:
        return (shared_phase + delta) % pitch, free_score, False
    # The frame's own best phase is outside the fence. Take the fence edge on
    # the side it wanted and record that we refused to follow it there.
    bounded = shared_phase + (window if delta > 0 else -window)
    return bounded % pitch, free_score, True


def correct_frame_phases(
    frames: Sequence[Image.Image],
    pitch: tuple[float, float],
    shared_phase: tuple[float, float],
    settings: PhaseSettings,
) -> list[FramePhase]:
    """One bounded phase per frame, relative to the state's shared lattice."""
    mode = str(settings.correction).lower()
    if mode not in {"bounded", "free", "off"}:
        raise ValueError(f"phase.correction must be bounded, free or off (got {settings.correction!r})")
    results: list[FramePhase] = []
    for index, frame in enumerate(frames):
        if mode == "off":
            results.append(FramePhase(index, (0.0, 0.0), shared_phase, False, (0.0, 0.0)))
            continue
        columns, rows = axis_edge_profiles(frame)
        effective = settings if mode == "bounded" else PhaseSettings(correction="free", tolerance=0.5, search_step=settings.search_step)
        phase_x, score_x, clamped_x = _search_axis(profile_to_list(columns), pitch[0], shared_phase[0], effective)
        phase_y, score_y, clamped_y = _search_axis(profile_to_list(rows), pitch[1], shared_phase[1], effective)
        offset = (
            _wrap_delta(phase_x - shared_phase[0], pitch[0]),
            _wrap_delta(phase_y - shared_phase[1], pitch[1]),
        )
        results.append(
            FramePhase(
                frame=index,
                offset=offset,
                applied=(phase_x, phase_y),
                clamped=clamped_x or clamped_y,
                score=(score_x, score_y),
            )
        )
    return results
