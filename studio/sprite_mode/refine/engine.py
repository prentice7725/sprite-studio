# SPDX-License-Identifier: MIT
"""Sprite Refine Engine v0.2 (spec §5).

    Shared Lattice Estimate
      -> Bounded Phase Correction
      -> Continuous Cell Weighting
      -> Oklab-consistent Sampling
      -> Thin-feature Preservation
      -> Residual Handoff to Repair Engine

The engine's contract, in the spec's words: *recover as much of the original
dot structure as possible in refine, and leave Repair only the small local
defects that remain.* Concretely that means this stage is allowed to choose a
grid, a phase within bounds, a palette, and a placement — and is not allowed to
paint, bridge, warp, or move a silhouette.

Ordering note: the lattice snap happens **before** placement. Snapping in the
raster the generator actually produced is what recovers true logical pixels;
placing first and snapping after would grid-lock an already-resampled image and
bake the resample error into the result.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from PIL import Image

from studio.shared.config import RefineSettings, load_refine_settings
from studio.shared.palette import apply_palette, build_palette, palette_distance_report

from .lattice import SharedLattice, estimate_shared_lattice
from .phase import correct_frame_phases
from .sampling import SampledFrame, content_heights, logical_bounds, residual_thin_features, sample_frames


@dataclass(frozen=True)
class SpriteRefineOutput:
    state: str
    frames: tuple[Image.Image, ...]
    logical_frames: tuple[Image.Image, ...]
    lattice: SharedLattice
    report: dict[str, Any]


class SpriteRefineEngine:
    """Animation-oriented refine. One lattice, bounded phases, one palette."""

    def __init__(self, settings: RefineSettings | None = None) -> None:
        self.settings = settings or load_refine_settings("sprite")
        if self.settings.mode != "sprite":
            raise ValueError(f"SpriteRefineEngine needs sprite settings, got {self.settings.mode!r}")

    def refine(
        self,
        frames: Sequence[Image.Image],
        *,
        state: str,
        cell_width: int,
        cell_height: int,
        safe_margin_x: int,
        safe_margin_y: int,
        locks: dict[str, str] | None = None,
        shared_lattice: SharedLattice | None = None,
    ) -> SpriteRefineOutput:
        if not frames:
            raise ValueError("cannot refine an empty frame set")
        if any(frame.size != (cell_width, cell_height) for frame in frames):
            raise ValueError("all extracted frames must match the working cell size")
        rgba = [frame.convert("RGBA") for frame in frames]
        locks = dict(locks or {})

        # A character-scoped lattice is passed in by the caller (it was estimated
        # across every state); a state-scoped one is estimated here. Either way the
        # frames of one state never disagree about cell pitch.
        lattice = shared_lattice or estimate_shared_lattice(rgba, self.settings.lattice)
        phases = correct_frame_phases(rgba, lattice.pitch, lattice.phase, self.settings.phase)
        sampled = sample_frames(rgba, lattice, phases, self.settings)

        logical_frames = [frame.logical for frame in sampled]
        palette = build_palette(logical_frames, self.settings.palette.colors)
        # Palette scope is "character" by default, but a state-level build is still
        # one palette for the whole row — the flicker this prevents is per-frame
        # requantisation, where the same armour colour lands on a different entry
        # each frame.
        quantised = [apply_palette(frame, palette) for frame in logical_frames]

        placed, placement = self._place(
            quantised, cell_width=cell_width, cell_height=cell_height,
            safe_margin_x=safe_margin_x, safe_margin_y=safe_margin_y,
        )
        report = self._report(
            state=state, lattice=lattice, sampled=sampled, palette=palette,
            placement=placement, locks=locks, logical_size=quantised[0].size,
        )
        return SpriteRefineOutput(
            state=state,
            frames=tuple(placed),
            logical_frames=tuple(quantised),
            lattice=lattice,
            report=report,
        )

    def _place(
        self,
        logical_frames: Sequence[Image.Image],
        *,
        cell_width: int,
        cell_height: int,
        safe_margin_x: int,
        safe_margin_y: int,
    ) -> tuple[list[Image.Image], dict[str, Any]]:
        """Integer-scale every frame into the cell on one shared baseline.

        The scale is an integer and shared across the row. Integer, because a
        fractional NEAREST resize re-introduces exactly the uneven block widths
        the lattice snap just removed; shared, because a per-frame scale is the
        classic size-breathing artifact — the character pulsing between frames.
        """
        boxes = [frame.getchannel("A").getbbox() for frame in logical_frames]
        present = [box for box in boxes if box is not None]
        if not present:
            raise ValueError("every refined frame is empty")
        content_width = max(box[2] - box[0] for box in present)
        content_height = max(box[3] - box[1] for box in present)
        available_width = max(1, cell_width - safe_margin_x * 2)
        available_height = max(1, cell_height - safe_margin_y * 2)
        scale = max(1, min(available_width // max(1, content_width), available_height // max(1, content_height)))
        baseline_y = cell_height - safe_margin_y

        # One crop window for the whole row: cropping each frame to its own bbox
        # would re-centre every frame independently and turn a still pose into a
        # jitter. The union window keeps relative motion intact.
        left_bound = min(box[0] for box in present)
        right_bound = max(box[2] for box in present)
        bottom_bound = max(box[3] for box in present)
        top_bound = min(box[1] for box in present)
        window = (left_bound, top_bound, right_bound, bottom_bound)

        placed: list[Image.Image] = []
        for frame in logical_frames:
            cropped = frame.crop(window)
            sprite = cropped.resize((cropped.width * scale, cropped.height * scale), Image.Resampling.NEAREST)
            canvas = Image.new("RGBA", (cell_width, cell_height), (0, 0, 0, 0))
            canvas.alpha_composite(
                sprite,
                (max(0, (cell_width - sprite.width) // 2), max(0, baseline_y - sprite.height)),
            )
            placed.append(canvas)
        placement = {
            "scale": scale,
            "baseline_y": baseline_y,
            "pivot": {"x": 0.5, "y": round(baseline_y / cell_height, 6)},
            "crop_window": list(window),
            "content_size": [content_width, content_height],
        }
        return placed, placement

    def _report(
        self,
        *,
        state: str,
        lattice: SharedLattice,
        sampled: Sequence[SampledFrame],
        palette: Sequence[tuple[int, int, int, int]],
        placement: dict[str, Any],
        locks: dict[str, str],
        logical_size: tuple[int, int],
    ) -> dict[str, Any]:
        clamped = [frame.index for frame in sampled if frame.phase.clamped]
        return {
            "kind": "asset-studio-sprite-refine",
            "version": 2,
            "mode": "sprite",
            "state": state,
            "frame_count": len(sampled),
            "settings": self.settings.to_dict(),
            "lattice": lattice.to_dict(),
            "phases": [frame.phase.to_dict() for frame in sampled],
            "phase_clamped_frames": clamped,
            "thin_feature": {
                "enabled": self.settings.thin_feature.enabled,
                "protected_pixels": [frame.protection.protected_pixels for frame in sampled],
                "temporal_support": [frame.protection.temporal_support for frame in sampled],
                "rescued_cells": [frame.sample.rescued_cells for frame in sampled],
            },
            "sampling": [frame.sample.to_dict() for frame in sampled],
            "residuals": residual_thin_features(sampled),
            "locks": {
                "grid": locks.get("grid", lattice.scope),
                "palette": locks.get("palette", self.settings.palette.scope),
                "baseline": locks.get("baseline", "character"),
                "pivot": locks.get("pivot", "character"),
                "scale": locks.get("scale", "character"),
            },
            "shared": {
                "logical_size": [logical_size[0], logical_size[1]],
                "palette_colors": len(palette),
                "palette": [list(color) for color in palette],
                "palette_separation": palette_distance_report(palette),
                **placement,
            },
            "warnings": _warnings(lattice, sampled, clamped),
        }


def _warnings(lattice: SharedLattice, sampled: Sequence[SampledFrame], clamped: Sequence[int]) -> list[dict[str, Any]]:
    """Refine never fixes what it is unsure about — it says so."""
    warnings: list[dict[str, Any]] = []
    if not lattice.locked:
        warnings.append(
            {
                "code": "lattice-unlocked",
                "message": "no confident cell pitch across this state; frames were sampled 1:1 without grid snap",
            }
        )
    if clamped:
        warnings.append(
            {
                "code": "phase-clamped",
                "frames": list(clamped),
                "message": "these frames wanted a phase outside the animation-safe bound and were held at the bound",
            }
        )
    empty = [frame.index for frame in sampled if frame.sample.filled_cells == 0]
    if empty:
        warnings.append({"code": "empty-frame", "frames": empty, "message": "frame produced no filled logical cell"})
    return warnings


def estimate_character_lattice(
    frames_by_state: dict[str, Sequence[Image.Image]],
    settings: RefineSettings | None = None,
) -> SharedLattice:
    """One lattice for every state of a character (``lattice.scope = "character"``).

    Wider scope, same argument as §5.2: if idle and attack disagree about cell
    pitch, the dots change size the moment the character swings, which reads as
    the whole sprite resolution shifting mid-animation.
    """
    resolved = settings or load_refine_settings("sprite")
    pooled: list[Image.Image] = []
    for frames in frames_by_state.values():
        pooled.extend(frame.convert("RGBA") for frame in frames)
    if not pooled:
        raise ValueError("no frames to estimate a character lattice from")
    return estimate_shared_lattice(pooled, resolved.lattice)
