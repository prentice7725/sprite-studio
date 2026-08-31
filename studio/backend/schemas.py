# SPDX-License-Identifier: Apache-2.0
"""Small data contracts shared by the Studio services and UI.

``mode`` is the field that splits Asset Studio (spec §13.1). Every project
carries it, both modes share the common fields above the split, and each mode
adds only what it actually needs — Sprite gets directions/states/locks, Static
gets asset type/tileability/export size. Neither can silently inherit the
other's semantics because ``resolve_mode`` refuses anything undeclared.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from studio.shared.modes import SPRITE, STATIC, resolve_asset_type, resolve_mode


StatusCode = Literal["not-generated", "raw", "normalized", "extracted", "refined", "repaired", "warning", "failed", "accepted"]
StaticStatusCode = Literal["not-generated", "raw", "refined", "cleaned", "qa-warning", "exported", "failed"]


@dataclass(frozen=True)
class StudioRunConfig:
    """A Sprite Mode project (spec §13.2)."""

    run_id: str
    character_id: str
    provider: str
    base_image: Path | None
    directions: tuple[str, ...]
    mirrors: dict[str, str]
    states: dict[str, dict[str, Any]]
    cell_size: int = 256
    runtime_size: int = 48
    preset: str = "sword"
    description: str = ""
    generation_profile: str = "refine_first"
    background_policy: str = "auto"
    mode: str = SPRITE
    refine: dict[str, Any] = field(default_factory=dict)
    locks: dict[str, str] = field(default_factory=lambda: {
        "grid": "state",
        "palette": "character",
        "baseline": "character",
        "pivot": "character",
        "scale": "character",
    })

    def __post_init__(self) -> None:
        if resolve_mode(self.mode).id != SPRITE:
            raise ValueError("StudioRunConfig is the Sprite Mode contract; use StaticProjectConfig for static assets")


@dataclass(frozen=True)
class StaticProjectConfig:
    """A Static Mode project (spec §13.3)."""

    project_id: str
    provider: str
    asset_type: str = "PIXEL_SCENE"
    style_profile: str = "pixel_scene"
    description: str = ""
    base_image: Path | None = None
    tileable: bool = False
    export_size: tuple[int, int] = (1024, 1024)
    background_policy: str = "auto"
    layer_intent: str = "none"
    mode: str = STATIC
    refine: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if resolve_mode(self.mode).id != STATIC:
            raise ValueError("StaticProjectConfig is the Static Mode contract; use StudioRunConfig for sprites")
        # Normalising here rather than at every call site is what keeps an
        # invalid asset type from reaching a refine engine that would treat it
        # as a default.
        object.__setattr__(self, "asset_type", resolve_asset_type(STATIC, self.asset_type))


@dataclass(frozen=True)
class RunInfo:
    run_id: str
    path: Path
    character_id: str
    provider: str
    preset: str
    directions: tuple[str, ...]
    states: tuple[str, ...]
    cell_size: int
    runtime_size: int
    generation_profile: str = "refine_first"
    background_policy: str = "auto"
    mode: str = SPRITE
    refine: dict[str, Any] = field(default_factory=dict)
    locks: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class StaticProjectInfo:
    project_id: str
    path: Path
    provider: str
    asset_type: str
    style_profile: str
    tileable: bool
    export_size: tuple[int, int]
    description: str = ""
    layer_intent: str = "none"
    background_policy: str = "auto"
    mode: str = STATIC
    refine: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class QaIssue:
    severity: Literal["info", "warning", "error"]
    state: str
    frame: int | None
    code: str
    message: str
    suggested_action: str | None = None


@dataclass(frozen=True)
class ProviderStatus:
    name: str
    available: bool
    message: str
    detail: str | None = None


@dataclass
class StudioJob:
    id: str
    type: str
    status: str = "pending"
    message: str = ""
    started_at: str | None = None
    finished_at: str | None = None
    result: dict[str, Any] = field(default_factory=dict)
