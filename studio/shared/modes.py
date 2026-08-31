# SPDX-License-Identifier: Apache-2.0
"""Asset Studio mode registry (spec sections 0, 3, 18).

One Studio, two production modes. This module is the single place that knows
which modes exist, what each one produces, and which asset types belong to it,
so the backend and the UI cannot drift on the answer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


SPRITE = "sprite"
STATIC = "static"


@dataclass(frozen=True)
class ModeSpec:
    id: str
    title: str
    purpose: str
    asset_types: tuple[str, ...]
    pipeline: tuple[str, ...]
    ui_sections: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "purpose": self.purpose,
            "asset_types": list(self.asset_types),
            "pipeline": list(self.pipeline),
            "ui_sections": list(self.ui_sections),
        }


SPRITE_MODE = ModeSpec(
    id=SPRITE,
    title="Sprite Mode",
    purpose="consistent character/unit animation asset production",
    asset_types=("CHARACTER", "UNIT", "FX"),
    pipeline=(
        "INPUT", "GENERATE", "ROW_NORMALIZE", "FRAME_EXTRACT", "SPRITE_REFINE",
        "REPAIR_ANALYZE", "DETERMINISTIC_REPAIR", "TEMPORAL_REPAIR",
        "OPTIONAL_AI_MICRO_FIX", "SHARED_RE_LOCK", "ANIMATION_QA", "CURATION",
        "ATLAS_RUNTIME_EXPORT",
    ),
    ui_sections=("PROJECT", "GENERATE", "NORMALIZE", "EXTRACT", "REFINE", "REPAIR", "ANIMATION", "QA", "EXPORT"),
)

STATIC_MODE = ModeSpec(
    id=STATIC,
    title="Static Mode",
    purpose="background, tile, object and still-illustration production",
    asset_types=("PIXEL_SCENE", "TILE_SET", "PROP_OBJECT", "FLAT_SCENE"),
    pipeline=(
        "INPUT", "GENERATE", "LAYOUT_TILE_NORMALIZE", "STATIC_REFINE",
        "CLEANUP_STATIC_REPAIR", "TILEABILITY_CHECK", "LAYER_CUTOUT_PROCESS",
        "STATIC_QA", "EXPORT",
    ),
    ui_sections=("PROJECT", "GENERATE", "REFINE", "CLEANUP", "TILE_LAYER", "QA", "EXPORT"),
)

MODES: dict[str, ModeSpec] = {SPRITE_MODE.id: SPRITE_MODE, STATIC_MODE.id: STATIC_MODE}


def mode_ids() -> list[str]:
    return list(MODES)


def resolve_mode(mode: str | None) -> ModeSpec:
    """Look up a mode, refusing anything not declared here.

    No default: a project whose mode is missing or misspelled must not quietly
    become a Sprite project and get animation locks applied to a tile set.
    """
    if not mode:
        raise ValueError(f"mode is required; choose one of: {', '.join(MODES)}")
    key = str(mode).strip().lower()
    if key not in MODES:
        raise ValueError(f"unknown mode {mode!r}; choose one of: {', '.join(MODES)}")
    return MODES[key]


def resolve_asset_type(mode: str, asset_type: str | None) -> str:
    spec = resolve_mode(mode)
    if asset_type is None:
        return spec.asset_types[0]
    key = str(asset_type).strip().upper()
    if key not in spec.asset_types:
        raise ValueError(f"asset_type {asset_type!r} is not valid for {spec.title}; choose one of: {', '.join(spec.asset_types)}")
    return key
