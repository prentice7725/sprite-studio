# SPDX-License-Identifier: MIT
"""Grid evidence, weighting and sampling shared by both Refine Engines."""

from .edges import accumulate_edge_profiles, axis_edge_profiles, cell_count, grid_edges, profile_to_list
from .search import AxisFit, axis_seed, collapse_guard, combined_seed, expand_candidates, scan_axis
from .sampling import SampleReport, snap_to_lattice
from .weighting import cell_weight_grid, cell_weights, weight_curve

__all__ = [
    "AxisFit",
    "SampleReport",
    "axis_seed",
    "collapse_guard",
    "combined_seed",
    "expand_candidates",
    "scan_axis",
    "accumulate_edge_profiles",
    "axis_edge_profiles",
    "cell_count",
    "cell_weight_grid",
    "cell_weights",
    "grid_edges",
    "profile_to_list",
    "snap_to_lattice",
    "weight_curve",
]
