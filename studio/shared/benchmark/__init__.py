# SPDX-License-Identifier: MIT
"""Synthetic degradation benchmark - the objective gate for algorithm changes."""

from .degrade import DEGRADATIONS, catalogue, degrade
from .harness import (
    BenchmarkCase,
    BenchmarkReport,
    CaseResult,
    compare_runs,
    default_cases,
    run_benchmark,
    run_case,
    synthetic_scene,
    synthetic_sprite_row,
)
from .metrics import sprite_metrics, static_metrics, temporal_consistency

__all__ = [
    "DEGRADATIONS",
    "BenchmarkCase",
    "BenchmarkReport",
    "CaseResult",
    "catalogue",
    "compare_runs",
    "default_cases",
    "degrade",
    "run_benchmark",
    "run_case",
    "sprite_metrics",
    "static_metrics",
    "synthetic_scene",
    "synthetic_sprite_row",
    "temporal_consistency",
]
