# SPDX-License-Identifier: Apache-2.0
"""Static Refine Engine v0.2 (spec §8).

    Large-image Grid Search
      -> FFT Candidate Proposal
      -> Oklab Palette Mapping
      -> Scene Cleanup
      -> Tile / Seam-aware Processing
      -> Static Repair

Shares Sprite Mode's colour metric, weighting curve and sampler; shares none of
its animation machinery. There is no lattice to hold across frames, so phase is
free; there is no thin weapon to protect, so coverage is not relaxed; there is
a lot of image, so the grid search is candidate-driven.

The output is deliberately *logical* by default — the true-resolution pixel art
recovered from the generated raster. Upscaling back to a delivery size is an
export decision (§7.4), not a refine one, so it stays out of here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from PIL import Image

from studio.shared.config import RefineSettings, load_refine_settings
from studio.shared.grid import SampleReport, grid_edges, snap_to_lattice
from studio.static_mode.cleanup.scene_cleanup import cleanup_scene
from studio.static_mode.tile.seam import check_seams

from .fft_candidates import CellSizeCandidate, candidate_periods, propose_cell_sizes
from .palette import build_scene_palette, palette_usage, quantise_scene, tone_consistency
from .scene_sampling import SceneGrid, block_diagnostics, crop_to_grid, detect_scene_grid


@dataclass(frozen=True)
class StaticRefineOutput:
    asset_type: str
    logical: Image.Image
    grid: SceneGrid
    palette: tuple[tuple[int, int, int, int], ...]
    report: dict[str, Any]


class StaticRefineEngine:
    """Scene/tile-oriented refine: candidate-driven grid, palette, cleanup, seams."""

    def __init__(self, settings: RefineSettings | None = None) -> None:
        self.settings = settings or load_refine_settings("static")
        if self.settings.mode != "static":
            raise ValueError(f"StaticRefineEngine needs static settings, got {self.settings.mode!r}")

    def refine(
        self,
        image: Image.Image,
        *,
        asset_type: str = "PIXEL_SCENE",
        cleanup: bool = True,
        tile_align: bool = False,
    ) -> StaticRefineOutput:
        source = image.convert("RGBA")
        candidates = propose_cell_sizes(source, self.settings.fft, self.settings.lattice)
        grid = detect_scene_grid(
            source,
            self.settings.lattice,
            proposals_x=candidate_periods(candidates, axis="x"),
            proposals_y=candidate_periods(candidates, axis="y"),
        )
        crop_offset: tuple[int, int] | None = None
        if tile_align and grid.locked:
            # Trim to whole cells *before* sampling, in source pixels — that is the
            # only space where the cell pitch is meaningful. Cropping the logical
            # output instead would measure a source-space pitch against
            # already-downscaled pixels and cut in the wrong place on any
            # fractional pitch (which is most of them).
            source, crop_offset = crop_to_grid(source, grid)
        logical, sample = self._snap(source, grid)

        palette = build_scene_palette(logical, self.settings.palette, iterations=self.settings.color.cluster_iterations)
        quantised = quantise_scene(logical, palette, self.settings.dither)

        cleanup_report: dict[str, Any] = {}
        if cleanup:
            result = cleanup_scene(quantised, self.settings.cleanup)
            quantised, cleanup_report = result.image, result.report

        seam_report: dict[str, Any] | None = None
        if self.settings.seam.check:
            # Seams are checked on the logical output, not the source: a seam
            # measured before the grid snap is measuring the generator's
            # anti-aliasing, not the tile the project will actually ship.
            seam_report = check_seams(quantised, self.settings.seam).to_dict()

        report = self._report(
            asset_type=asset_type,
            source_size=image.size,
            grid=grid,
            candidates=candidates,
            sample=sample,
            palette=palette,
            quantised=quantised,
            cleanup_report=cleanup_report,
            seam_report=seam_report,
            blocks=block_diagnostics(source, grid) if grid.locked else [],
        )
        if crop_offset is not None:
            report["tile_crop_offset"] = list(crop_offset)
            report["tile_cropped_size"] = list(source.size)
        return StaticRefineOutput(
            asset_type=asset_type,
            logical=quantised,
            grid=grid,
            palette=tuple(palette),
            report=report,
        )

    def _snap(self, source: Image.Image, grid: SceneGrid) -> tuple[Image.Image, SampleReport]:
        width, height = source.size
        if not grid.locked:
            # Same rule as Sprite Mode: an unconfident grid means no snap. The
            # scene passes through at 1:1 and the report says why.
            x_edges = list(range(width + 1))
            y_edges = list(range(height + 1))
        else:
            x_edges = grid_edges(width, grid.pitch[0], grid.phase[0])
            y_edges = grid_edges(height, grid.pitch[1], grid.phase[1])
        return snap_to_lattice(
            source, x_edges, y_edges,
            weighting=self.settings.weighting,
            color=self.settings.color,
        )

    def _report(
        self,
        *,
        asset_type: str,
        source_size: tuple[int, int],
        grid: SceneGrid,
        candidates: list[CellSizeCandidate],
        sample: SampleReport,
        palette: tuple[tuple[int, int, int, int], ...],
        quantised: Image.Image,
        cleanup_report: dict[str, Any],
        seam_report: dict[str, Any] | None,
        blocks: list[dict[str, Any]],
    ) -> dict[str, Any]:
        warnings: list[dict[str, Any]] = []
        if not grid.locked:
            warnings.append(
                {
                    "code": "grid-unlocked",
                    "message": "no confident cell pitch in this scene; it was sampled 1:1 without grid snap",
                }
            )
        disagreeing = [entry["block"] for entry in blocks if not entry["agrees"]]
        if disagreeing:
            warnings.append(
                {
                    "code": "grid-uneven",
                    "blocks": disagreeing,
                    "message": "these regions do not share the scene's cell pitch; consider cropping and refining them separately",
                }
            )
        if seam_report is not None and not seam_report["ok"]:
            warnings.append(
                {
                    "code": "seam-open",
                    "message": "tile edges do not meet within threshold; run seam repair or regenerate",
                }
            )
        return {
            "kind": "asset-studio-static-refine",
            "version": 2,
            "mode": "static",
            "asset_type": asset_type,
            "source_size": [source_size[0], source_size[1]],
            "settings": self.settings.to_dict(),
            "grid": grid.to_dict(),
            "fft_candidates": [item.to_dict() for item in candidates],
            "sampling": sample.to_dict(),
            "palette": {
                "colors": len(palette),
                "entries": [list(color) for color in palette],
                "usage": palette_usage(quantised, palette),
                "dither": self.settings.dither.mode,
            },
            "tone": tone_consistency(quantised),
            "cleanup": cleanup_report,
            "seam": seam_report,
            "blocks": blocks,
            "warnings": warnings,
        }
