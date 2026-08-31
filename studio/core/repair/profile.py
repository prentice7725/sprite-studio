# SPDX-License-Identifier: Apache-2.0
"""Configurable safety policy for repair analysis and application."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RepairProfile:
    alpha_threshold: int = 16
    max_hole_pixels: int = 3
    max_orphan_pixels: int = 1
    temporal_search_radius: int = 3
    max_added_pixels: int = 24
    max_added_ratio: float = 0.01
    apply_small_holes: bool = True
    apply_temporal: bool = True
    safe_thresholds: dict[str, float] = field(default_factory=lambda: {
        "small_hole": 0.96,
        "outline_gap": 0.98,
        "orphan_pixel": 0.96,
        "thin_feature_break": 0.97,
        "temporal_missing_pixel": 0.97,
    })
    # Normalized against the occupied sprite bbox, not the whole canvas.
    # The default keeps face holes (eyes/mouth) out of unattended repair.
    protected_regions: tuple[tuple[float, float, float, float], ...] = ((0.25, 0.0, 0.75, 0.30),)

    @classmethod
    def from_mapping(cls, value: dict[str, Any] | None) -> "RepairProfile":
        value = dict(value or {})
        base = cls()
        thresholds = dict(base.safe_thresholds)
        thresholds.update({str(k): float(v) for k, v in (value.get("safe_thresholds") or {}).items()})
        regions = value.get("protected_regions", base.protected_regions)
        return cls(
            alpha_threshold=int(value.get("alpha_threshold", base.alpha_threshold)),
            max_hole_pixels=int(value.get("max_hole_pixels", base.max_hole_pixels)),
            max_orphan_pixels=int(value.get("max_orphan_pixels", base.max_orphan_pixels)),
            temporal_search_radius=int(value.get("temporal_search_radius", base.temporal_search_radius)),
            max_added_pixels=int(value.get("max_added_pixels", base.max_added_pixels)),
            max_added_ratio=float(value.get("max_added_ratio", base.max_added_ratio)),
            apply_small_holes=bool(value.get("apply_small_holes", base.apply_small_holes)),
            apply_temporal=bool(value.get("apply_temporal", base.apply_temporal)),
            safe_thresholds=thresholds,
            protected_regions=tuple(tuple(float(number) for number in region) for region in regions),
        )
