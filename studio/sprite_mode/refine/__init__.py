# SPDX-License-Identifier: MIT
"""Sprite Mode Refine Engine v0.2 - animation-oriented refine."""

from .engine import SpriteRefineEngine, SpriteRefineOutput, estimate_character_lattice
from .lattice import SharedLattice, estimate_shared_lattice
from .phase import FramePhase, correct_frame_phases
from .sampling import SampledFrame, sample_frames, shift_edges
from .thin_feature import ThinFeatureMask, thin_feature_mask, with_temporal_support

__all__ = [
    "FramePhase",
    "SampledFrame",
    "SharedLattice",
    "SpriteRefineEngine",
    "SpriteRefineOutput",
    "ThinFeatureMask",
    "correct_frame_phases",
    "estimate_character_lattice",
    "estimate_shared_lattice",
    "sample_frames",
    "shift_edges",
    "thin_feature_mask",
    "with_temporal_support",
]
