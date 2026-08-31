# SPDX-License-Identifier: Apache-2.0
"""Static Mode Refine Engine v0.2 - scene/tile-oriented refine."""

from .dither import DITHER_MODES, apply_dither
from .engine import StaticRefineEngine, StaticRefineOutput
from .fft_candidates import CellSizeCandidate, candidate_periods, propose_cell_sizes
from .palette import build_scene_palette, palette_usage, quantise_scene, tone_consistency
from .scene_sampling import SceneGrid, block_diagnostics, crop_to_grid, detect_scene_grid, edge_density

__all__ = [
    "DITHER_MODES",
    "CellSizeCandidate",
    "SceneGrid",
    "StaticRefineEngine",
    "StaticRefineOutput",
    "apply_dither",
    "block_diagnostics",
    "build_scene_palette",
    "candidate_periods",
    "crop_to_grid",
    "detect_scene_grid",
    "edge_density",
    "palette_usage",
    "propose_cell_sizes",
    "quantise_scene",
    "tone_consistency",
]
