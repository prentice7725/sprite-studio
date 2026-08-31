# SPDX-License-Identifier: Apache-2.0
"""Refine settings as data — spec §3.2 bans hardcoded thresholds.

Every number the two Refine Engines steer by (grid search range, phase
tolerance, FFT candidate count, palette size, dither mode, seam threshold)
arrives from ``studio/data/config/<mode>_refine.json`` and may be overridden
per project. The dataclasses below are the typed shape of that file; loading is
strict — an unknown section or a malformed anchor curve fails loudly rather
than falling back to a built-in default nobody can see (No Silent Fallback).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, fields, is_dataclass, replace
from pathlib import Path
from typing import Any


CONFIG_DIR = Path(__file__).resolve().parents[2] / "data" / "config"


@dataclass(frozen=True)
class LatticeSettings:
    scope: str = "state"
    max_pitch: int = 48
    min_pitch: float = 2.0
    search_half_span: float = 0.75
    search_step: float = 0.02
    confidence_floor: float = 0.2
    coarse_to_fine: bool = False
    large_image_pixels: int = 262144


@dataclass(frozen=True)
class PhaseSettings:
    correction: str = "bounded"
    tolerance: float = 0.35
    search_step: float = 0.05


@dataclass(frozen=True)
class WeightingSettings:
    mode: str = "continuous"
    anchors: tuple[tuple[float, float], ...] = ((0.0, 1.0), (0.5, 0.7), (0.8, 0.3), (1.0, 0.1))
    coverage_threshold: float = 0.5


@dataclass(frozen=True)
class ColorSettings:
    metric: str = "oklab"
    cluster_iterations: int = 6
    detail_bias: bool = True
    detail_bias_share: float = 0.4
    detail_bias_lightness_gap: float = 0.25
    detail_bias_max_lightness: float = 0.45


@dataclass(frozen=True)
class ThinFeatureSettings:
    enabled: bool = True
    max_thickness: int = 2
    coverage_relief: float = 0.28
    temporal_evidence: bool = True


@dataclass(frozen=True)
class PaletteSettings:
    colors: int = 16
    scope: str = "character"


@dataclass(frozen=True)
class FftSettings:
    candidate_search: bool = False
    candidates: int = 4
    min_prominence: float = 0.15


@dataclass(frozen=True)
class DitherSettings:
    mode: str = "off"
    strength: float = 1.0
    matrix: int = 4


@dataclass(frozen=True)
class SeamSettings:
    check: bool = False
    threshold: float = 0.08
    band: int = 1


@dataclass(frozen=True)
class CleanupSettings:
    orphan_max_area: int = 2
    fringe_alpha_threshold: int = 128


@dataclass(frozen=True)
class RefineSettings:
    mode: str
    lattice: LatticeSettings = field(default_factory=LatticeSettings)
    phase: PhaseSettings = field(default_factory=PhaseSettings)
    weighting: WeightingSettings = field(default_factory=WeightingSettings)
    color: ColorSettings = field(default_factory=ColorSettings)
    thin_feature: ThinFeatureSettings = field(default_factory=ThinFeatureSettings)
    palette: PaletteSettings = field(default_factory=PaletteSettings)
    fft: FftSettings = field(default_factory=FftSettings)
    dither: DitherSettings = field(default_factory=DitherSettings)
    seam: SeamSettings = field(default_factory=SeamSettings)
    cleanup: CleanupSettings = field(default_factory=CleanupSettings)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"mode": self.mode}
        for item in fields(self):
            if item.name != "mode":
                payload[item.name] = _section_to_dict(getattr(self, item.name))
        return payload


# Static Mode spells its lattice section "grid" (spec §8.1 "Large-image Grid
# Search"); Sprite Mode spells it "lattice" (§5.2). One settings field holds
# both so no engine has to branch on which spelling a project file used.
_SECTION_TYPES: dict[str, type] = {
    "lattice": LatticeSettings,
    "grid": LatticeSettings,
    "phase": PhaseSettings,
    "weighting": WeightingSettings,
    "color": ColorSettings,
    "thin_feature": ThinFeatureSettings,
    "palette": PaletteSettings,
    "fft": FftSettings,
    "dither": DitherSettings,
    "seam": SeamSettings,
    "cleanup": CleanupSettings,
}


def _section_to_dict(section: Any) -> Any:
    if not is_dataclass(section):
        return section
    out: dict[str, Any] = {}
    for item in fields(section):
        value = getattr(section, item.name)
        out[item.name] = [list(pair) for pair in value] if item.name == "anchors" else value
    return out


def _build_section(name: str, payload: dict[str, Any]) -> Any:
    cls = _SECTION_TYPES[name]
    known = {item.name for item in fields(cls)}
    unknown = set(payload) - known
    if unknown:
        raise ValueError(f"refine config section {name!r} has unknown keys: {sorted(unknown)}")
    values = dict(payload)
    if "anchors" in values:
        values["anchors"] = _normalize_anchors(values["anchors"])
    return cls(**values)


def _normalize_anchors(raw: Any) -> tuple[tuple[float, float], ...]:
    """Validate the continuous-weighting falloff curve (spec §5.4).

    The curve is the whole point of the small-cell fix, so a malformed one is
    an error rather than a clamp: an unsorted or non-spanning anchor list would
    otherwise interpolate to weights nobody intended and quietly reintroduce
    the hard-cut artifacts the curve exists to remove.
    """
    if not isinstance(raw, (list, tuple)) or len(raw) < 2:
        raise ValueError("weighting.anchors needs at least two [radius, weight] pairs")
    anchors: list[tuple[float, float]] = []
    for pair in raw:
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            raise ValueError("weighting.anchors entries must be [radius, weight] pairs")
        radius, weight = float(pair[0]), float(pair[1])
        if not 0.0 <= radius <= 1.0 or not 0.0 <= weight <= 1.0:
            raise ValueError("weighting.anchors radius and weight must both be within [0, 1]")
        anchors.append((radius, weight))
    if [anchor[0] for anchor in anchors] != sorted(anchor[0] for anchor in anchors):
        raise ValueError("weighting.anchors must be sorted by increasing radius")
    if anchors[0][0] != 0.0 or anchors[-1][0] != 1.0:
        raise ValueError("weighting.anchors must span radius 0.0 to 1.0")
    return tuple(anchors)


def settings_from_dict(mode: str, payload: dict[str, Any]) -> RefineSettings:
    """Build settings from a parsed config document. Unknown sections are errors."""
    sections = {key: value for key, value in payload.items() if key not in {"kind", "mode", "version"}}
    unknown = set(sections) - set(_SECTION_TYPES)
    if unknown:
        raise ValueError(f"refine config has unknown sections: {sorted(unknown)}")
    built: dict[str, Any] = {}
    for name, value in sections.items():
        if not isinstance(value, dict):
            raise ValueError(f"refine config section {name!r} must be an object")
        built["lattice" if name == "grid" else name] = _build_section(name, value)
    return RefineSettings(mode=mode, **built)


def load_refine_settings(mode: str, *, config_dir: Path | None = None) -> RefineSettings:
    directory = config_dir or CONFIG_DIR
    path = directory / f"{mode}_refine.json"
    if not path.is_file():
        raise ValueError(f"no refine config for mode {mode!r}: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"refine config must be an object: {path}")
    declared = payload.get("mode")
    if declared is not None and declared != mode:
        raise ValueError(f"refine config at {path} declares mode {declared!r}, loaded as {mode!r}")
    return settings_from_dict(mode, payload)


# The spec's project JSON writes overrides flat (§13.2 "refine": {"phase_correction":
# "bounded", ...}). Sectioned overrides are accepted too; this table is the bridge so
# neither the project schema nor the settings shape has to bend toward the other.
_FLAT_OVERRIDES: dict[str, tuple[str, str]] = {
    "shared_lattice_scope": ("lattice", "scope"),
    "phase_correction": ("phase", "correction"),
    "phase_tolerance": ("phase", "tolerance"),
    "cell_weighting": ("weighting", "mode"),
    "color_metric": ("color", "metric"),
    "fft_candidate_search": ("fft", "candidate_search"),
    "fft_candidates": ("fft", "candidates"),
    "palette_colors": ("palette", "colors"),
    "dither_mode": ("dither", "mode"),
    "dither_strength": ("dither", "strength"),
    "seam_check": ("seam", "check"),
    "seam_threshold": ("seam", "threshold"),
    "thin_feature_protection": ("thin_feature", "enabled"),
    "grid_max_pitch": ("lattice", "max_pitch"),
}


def apply_overrides(settings: RefineSettings, overrides: dict[str, Any] | None) -> RefineSettings:
    """Layer a project's ``refine`` block over the mode defaults.

    An unrecognised key is an error, never a silently ignored setting — a typo
    in a project file must not read as "the operator left it at the default".
    """
    if not overrides:
        return settings
    updates: dict[str, dict[str, Any]] = {}
    for key, value in overrides.items():
        if key in _FLAT_OVERRIDES:
            section, attribute = _FLAT_OVERRIDES[key]
            updates.setdefault(section, {})[attribute] = value
            continue
        if key in _SECTION_TYPES and isinstance(value, dict):
            updates.setdefault("lattice" if key == "grid" else key, {}).update(value)
            continue
        raise ValueError(f"unknown refine override: {key!r}")
    result = settings
    for section, payload in updates.items():
        current = getattr(result, section)
        merged = {item.name: getattr(current, item.name) for item in fields(current)}
        unknown = set(payload) - set(merged)
        if unknown:
            raise ValueError(f"unknown refine override keys for {section!r}: {sorted(unknown)}")
        merged.update(payload)
        if "anchors" in payload:
            merged["anchors"] = _normalize_anchors(payload["anchors"])
        result = replace(result, **{section: type(current)(**merged)})
    return result
