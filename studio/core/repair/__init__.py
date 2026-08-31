# SPDX-License-Identifier: MIT
"""Local and temporal repair for refined sprite frames."""

from .analyzer import RepairAnalyzer
from .engine import DeterministicRepairEngine
from .models import RepairCandidate, RepairChange, RepairResult
from .profile import RepairProfile
from .repair_pipeline import RepairPipeline
from .temporal import TemporalRepairEngine
from .thin_feature import ThinFeatureAnalyzer

__all__ = [
    "DeterministicRepairEngine", "RepairAnalyzer", "RepairCandidate", "RepairChange",
    "RepairPipeline", "RepairProfile", "RepairResult", "TemporalRepairEngine", "ThinFeatureAnalyzer",
]
