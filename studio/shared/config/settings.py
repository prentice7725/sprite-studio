# SPDX-License-Identifier: Apache-2.0
"""Refine, QA and Benchmark settings as data — spec §3.2 bans hardcoded thresholds.

Every number the two Refine Engines steer by (grid search range, phase
tolerance, FFT candidate count, palette size, dither mode, seam threshold)
arrives from ``studio/data/config/<mode>_refine.json`` and may be overridden
per project. The dataclasses below are the typed shape of that file; loading is
strict — an unknown section, an unknown key, or a malformed anchor curve
fails loudly rather than falling back to a built-in default nobody can see (No Silent Fallback).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, fields, is_dataclass, replace
from pathlib import Path
from typing import Any


CONFIG_DIR = Path(__file__).resolve().parents[2] / "data" / "config"


@dataclass(frozen=True)
class LatticeSettings:
    scope: str
    max_pitch: int
    min_pitch: float
    search_half_span: float
    search_step: float
    confidence_floor: float
    coarse_to_fine: bool
    large_image_pixels: int

    def __post_init__(self) -> None:
        if self.min_pitch < 1.0 or self.max_pitch < self.min_pitch:
            raise ValueError(f"invalid pitch range: min_pitch={self.min_pitch}, max_pitch={self.max_pitch}")
        if not (0.0 <= self.confidence_floor <= 1.0):
            raise ValueError(f"confidence_floor must be in [0, 1], got {self.confidence_floor}")
        if self.search_step <= 0:
            raise ValueError(f"search_step must be positive, got {self.search_step}")


@dataclass(frozen=True)
class PhaseSettings:
    correction: str
    tolerance: float
    search_step: float

    def __post_init__(self) -> None:
        if self.tolerance < 0:
            raise ValueError(f"phase tolerance must be non-negative, got {self.tolerance}")
        if self.search_step <= 0:
            raise ValueError(f"phase search_step must be positive, got {self.search_step}")


@dataclass(frozen=True)
class WeightingSettings:
    mode: str
    anchors: tuple[tuple[float, float], ...]
    coverage_threshold: float

    def __post_init__(self) -> None:
        if not (0.0 < self.coverage_threshold <= 1.0):
            raise ValueError(f"coverage_threshold must be in (0, 1], got {self.coverage_threshold}")


@dataclass(frozen=True)
class ColorSettings:
    metric: str
    cluster_iterations: int
    detail_bias: bool
    detail_bias_share: float
    detail_bias_lightness_gap: float
    detail_bias_max_lightness: float

    def __post_init__(self) -> None:
        if self.metric != "oklab":
            raise ValueError(f"only oklab color metric is supported, got {self.metric!r}")
        if self.cluster_iterations < 1:
            raise ValueError(f"cluster_iterations must be >= 1, got {self.cluster_iterations}")


@dataclass(frozen=True)
class ThinFeatureSettings:
    enabled: bool
    max_thickness: int
    coverage_relief: float
    temporal_evidence: bool

    def __post_init__(self) -> None:
        if self.max_thickness < 1:
            raise ValueError(f"max_thickness must be >= 1, got {self.max_thickness}")
        if not (0.0 <= self.coverage_relief <= 1.0):
            raise ValueError(f"coverage_relief must be in [0, 1], got {self.coverage_relief}")


@dataclass(frozen=True)
class PaletteSettings:
    colors: int
    scope: str

    def __post_init__(self) -> None:
        if self.colors < 2:
            raise ValueError(f"palette colors must be >= 2, got {self.colors}")


@dataclass(frozen=True)
class FftSettings:
    candidate_search: bool
    candidates: int
    min_prominence: float

    def __post_init__(self) -> None:
        if self.candidates < 1:
            raise ValueError(f"fft candidates must be >= 1, got {self.candidates}")
        if not (0.0 <= self.min_prominence <= 1.0):
            raise ValueError(f"min_prominence must be in [0, 1], got {self.min_prominence}")


@dataclass(frozen=True)
class DitherSettings:
    mode: str
    strength: float
    matrix: int
    # Structural optional: `None` means "no named preset was applied" (a
    # diagnostic/provenance field, not a tuning value) — §2.3 permits omitting
    # this key from committed config, unlike every other field on this class.
    preset: str | None = field(default=None, metadata={"structural_optional": True})

    def __post_init__(self) -> None:
        if self.matrix < 2:
            raise ValueError(f"dither matrix must be >= 2, got {self.matrix}")


@dataclass(frozen=True)
class SeamSettings:
    check: bool
    threshold: float
    band: int

    def __post_init__(self) -> None:
        if self.threshold < 0:
            raise ValueError(f"seam threshold must be non-negative, got {self.threshold}")
        if self.band < 1:
            raise ValueError(f"seam band must be >= 1, got {self.band}")


@dataclass(frozen=True)
class CleanupSettings:
    orphan_max_area: int
    fringe_alpha_threshold: int

    def __post_init__(self) -> None:
        if self.orphan_max_area < 0:
            raise ValueError(f"orphan_max_area must be non-negative, got {self.orphan_max_area}")
        if not (0 <= self.fringe_alpha_threshold <= 255):
            raise ValueError(f"fringe_alpha_threshold must be in [0, 255], got {self.fringe_alpha_threshold}")


@dataclass(frozen=True)
class RefineSettings:
    # No default_factory here on purpose (§2.2): every section is a required
    # part of a mode's committed config, checked by `settings_from_dict`
    # before this constructor ever runs. A default_factory would silently
    # construct e.g. `DitherSettings()` for a config that never mentioned
    # dither at all — exactly the hidden fallback §2 bans.
    mode: str
    lattice: LatticeSettings
    phase: PhaseSettings
    weighting: WeightingSettings
    color: ColorSettings
    thin_feature: ThinFeatureSettings
    palette: PaletteSettings
    fft: FftSettings
    dither: DitherSettings
    seam: SeamSettings
    cleanup: CleanupSettings

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"mode": self.mode}
        for item in fields(self):
            if item.name != "mode":
                payload[item.name] = _section_to_dict(getattr(self, item.name))
        return payload


@dataclass(frozen=True)
class SpriteQaSettings:
    baseline_tolerance: float
    scale_jump_ratio: float
    duplicate_threshold: int
    side_balance_threshold: int
    min_frames: int

    def __post_init__(self) -> None:
        if self.baseline_tolerance < 0:
            raise ValueError("baseline_tolerance must be non-negative")
        if not (0.0 <= self.scale_jump_ratio <= 1.0):
            raise ValueError("scale_jump_ratio must be in [0, 1]")


@dataclass(frozen=True)
class StaticQaSettings:
    soft_ratio_threshold: float
    min_delta_e_threshold: float
    orphan_max_area: int
    fringe_alpha_threshold: int
    fill_max_area: int
    min_layers: int

    def __post_init__(self) -> None:
        if not (0.0 <= self.soft_ratio_threshold <= 1.0):
            raise ValueError("soft_ratio_threshold must be in [0, 1]")
        if self.min_delta_e_threshold < 0:
            raise ValueError("min_delta_e_threshold must be non-negative")


@dataclass(frozen=True)
class MetricGateSettings:
    direction: str  # "higher" or "lower"
    tolerance: float
    gate: bool

    def __post_init__(self) -> None:
        if self.direction not in {"higher", "lower"}:
            raise ValueError(f"direction must be 'higher' or 'lower', got {self.direction!r}")
        if self.tolerance < 0:
            raise ValueError("tolerance must be non-negative")


@dataclass(frozen=True)
class MetricPolicySettings:
    """SSOT for the policy constants benchmark metrics were hardcoding in
    several places independently (§5) — an image-processing *definition*
    (squared vs. root distance, 8-bit channel max) stays in code; a threshold
    someone picked (what counts as "opaque", "retained", "collapsed") is data.
    """
    alpha_opaque_threshold: int
    palette_retained_delta_e: float
    texture_collapse_ratio: float

    def __post_init__(self) -> None:
        if not (0 <= self.alpha_opaque_threshold <= 255):
            raise ValueError(f"alpha_opaque_threshold must be in [0, 255], got {self.alpha_opaque_threshold}")
        if self.palette_retained_delta_e < 0:
            raise ValueError("palette_retained_delta_e must be non-negative")
        if not (0.0 <= self.texture_collapse_ratio <= 1.0):
            raise ValueError(f"texture_collapse_ratio must be in [0, 1], got {self.texture_collapse_ratio}")


@dataclass(frozen=True)
class BenchmarkSettings:
    # Required, no default (§2/§5): the whole point is that 128 / 0.02 / 0.25
    # live in committed JSON, not as a class-level fallback nobody sees.
    # (Declared first — a dataclass can't follow a defaulted field with one.)
    metric_policy: MetricPolicySettings
    sprite: dict[str, MetricGateSettings] = field(default_factory=dict)
    static: dict[str, MetricGateSettings] = field(default_factory=dict)


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


def _required_field_names(cls: type) -> set[str]:
    """Field names that must appear in committed JSON for ``cls``.

    A field is exempt only when explicitly marked
    ``metadata={"structural_optional": True}`` (§2.3: optional diagnostic /
    provenance fields, not tuning values) — never merely because the
    dataclass happens to have a default.
    """
    return {item.name for item in fields(cls) if not item.metadata.get("structural_optional")}


def _check_keys(label: str, cls: type, payload: dict[str, Any]) -> None:
    """Fail loudly on both an unknown key (typo) and a missing required key
    (silent-fallback risk) — §1/§2's "no silent fallback" applied uniformly
    to every typed config section, not just the ones that happened to get a
    ``__post_init__`` range check."""
    known = {item.name for item in fields(cls)}
    payload_keys = set(payload)
    unknown = payload_keys - known
    if unknown:
        raise ValueError(f"{label} has unknown keys: {sorted(unknown)}")
    missing = _required_field_names(cls) - payload_keys
    if missing:
        raise ValueError(f"{label} missing required keys: {sorted(missing)}")


def _build_section(name: str, payload: dict[str, Any]) -> Any:
    cls = _SECTION_TYPES[name]
    _check_keys(f"refine config section {name!r}", cls, payload)
    values = dict(payload)
    if "anchors" in values:
        values["anchors"] = _normalize_anchors(values["anchors"])
    return cls(**values)


def _normalize_anchors(raw: Any) -> tuple[tuple[float, float], ...]:
    """Validate the continuous-weighting falloff curve (spec §5.4)."""
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


# §2.2: every mode requires the full section set — a mode-specific "no dither
# section at all" is not a shorter config, it is the exact hidden fallback
# (`DitherSettings()` defaults) §2 is meant to eliminate. Sprite's `dither`/
# `seam` sections are typically inert (mode="off", check=false) but must
# still be spelled out in the committed JSON.
_REQUIRED_SECTIONS: dict[str, tuple[str, ...]] = {
    "sprite": ("lattice", "phase", "weighting", "color", "thin_feature", "palette", "fft", "dither", "seam", "cleanup"),
    "static": ("lattice", "phase", "weighting", "color", "thin_feature", "palette", "fft", "dither", "seam", "cleanup"),
}


def settings_from_dict(mode: str, payload: dict[str, Any]) -> RefineSettings:
    """Build settings from a parsed config document.

    Unknown sections, an unknown/missing key *within* a present section, and
    a missing *required section* are all errors — §2.1/§2.2. Present
    sections are validated (and so report their own specific defect first)
    before the whole-config completeness check runs, so a config that is
    both incomplete and internally wrong reports the more specific problem.
    """
    sections = {key: value for key, value in payload.items() if key not in {"kind", "mode", "version"}}
    unknown = set(sections) - set(_SECTION_TYPES)
    if unknown:
        raise ValueError(f"refine config has unknown sections: {sorted(unknown)}")
    required = _REQUIRED_SECTIONS.get(mode)
    if required is None:
        raise ValueError(f"unknown refine mode {mode!r}; no required-section list registered")
    built: dict[str, Any] = {}
    for name, value in sections.items():
        if not isinstance(value, dict):
            raise ValueError(f"refine config section {name!r} must be an object")
        built["lattice" if name == "grid" else name] = _build_section(name, value)
    present = {"lattice" if key == "grid" else key for key in sections}
    missing = [name for name in required if name not in present]
    if missing:
        raise ValueError(f"{mode} refine config missing required section(s): {missing}")
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


def load_qa_settings(mode: str, *, config_dir: Path | None = None) -> SpriteQaSettings | StaticQaSettings:
    directory = config_dir or CONFIG_DIR
    path = directory / f"{mode}_qa.json"
    if not path.is_file():
        raise ValueError(f"no QA config for mode {mode!r}: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"QA config must be an object: {path}")
    values = {k: v for k, v in payload.items() if k not in {"kind", "mode", "version"}}
    if mode == "sprite":
        _check_keys(f"sprite QA config ({path})", SpriteQaSettings, values)
        return SpriteQaSettings(**values)
    if mode == "static":
        _check_keys(f"static QA config ({path})", StaticQaSettings, values)
        return StaticQaSettings(**values)
    raise ValueError(f"unknown QA mode: {mode!r}")


def load_normalize_quality_settings(mode: str = "sprite", *, config_dir: Path | None = None) -> "NormalizeQualityPolicy":
    """Grok row normalization's Subject Validity / Row-Level Acceptance Gate
    thresholds (`SPRITE_STUDIO_GENERATION_NORMALIZE_HARDENING_DIRECTIVE.md` §14).

    Only sprite mode normalizes component rows; static mode has no equivalent
    config. Parsing itself is owned by the engine module so the range/shape
    validation lives in one place — this loader only resolves the file and
    hands its parsed JSON to ``NormalizeQualityPolicy.from_dict`` (fail-loud,
    same as ``load_qa_settings``: no config file, no policy, no silent
    built-in fallback for production).
    """
    from sprite_studio.gen.normalize_quality import NormalizeQualityPolicy

    if mode != "sprite":
        raise ValueError(f"unknown normalize_quality mode: {mode!r}")
    directory = config_dir or CONFIG_DIR
    path = directory / f"{mode}_normalize_quality.json"
    if not path.is_file():
        raise ValueError(f"no normalize_quality config for mode {mode!r}: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"normalize_quality config must be an object: {path}")
    declared = payload.get("mode")
    if declared is not None and declared != mode:
        raise ValueError(f"normalize_quality config at {path} declares mode {declared!r}, loaded as {mode!r}")
    return NormalizeQualityPolicy.from_dict(payload)


def load_benchmark_settings(*, config_dir: Path | None = None) -> BenchmarkSettings:
    directory = config_dir or CONFIG_DIR
    path = directory / "benchmark.json"
    if not path.is_file():
        raise ValueError(f"no benchmark config found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"benchmark config must be an object: {path}")
    def _build_rules(mode_key: str) -> dict[str, MetricGateSettings]:
        rules = {}
        for metric_name, gate_payload in payload.get(mode_key, {}).items():
            if not isinstance(gate_payload, dict):
                raise ValueError(f"benchmark config {mode_key}.{metric_name!r} must be an object")
            _check_keys(f"benchmark config {mode_key}.{metric_name!r}", MetricGateSettings, gate_payload)
            rules[metric_name] = MetricGateSettings(**gate_payload)
        return rules

    metric_policy_payload = payload.get("metric_policy")
    if not isinstance(metric_policy_payload, dict):
        raise ValueError(f"benchmark config missing required section 'metric_policy': {path}")
    _check_keys("benchmark config 'metric_policy'", MetricPolicySettings, metric_policy_payload)
    metric_policy = MetricPolicySettings(**metric_policy_payload)

    return BenchmarkSettings(metric_policy=metric_policy, sprite=_build_rules("sprite"), static=_build_rules("static"))


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
