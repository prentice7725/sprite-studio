# SPDX-License-Identifier: Apache-2.0
"""Test strict validation of configuration files across Refine, QA, and Benchmark."""

from __future__ import annotations

from dataclasses import MISSING, fields

import pytest

from studio.shared.config import (
    apply_overrides,
    load_benchmark_settings,
    load_normalize_quality_settings,
    load_qa_settings,
    load_refine_settings,
    settings_from_dict,
)
from studio.shared.config.settings import CONFIG_DIR, _REQUIRED_SECTIONS, _SECTION_TYPES, _required_field_names


def test_load_all_configs_valid():
    sprite_refine = load_refine_settings("sprite")
    assert sprite_refine.mode == "sprite"
    assert sprite_refine.lattice.min_pitch >= 1.0

    static_refine = load_refine_settings("static")
    assert static_refine.mode == "static"

    sprite_qa = load_qa_settings("sprite")
    assert sprite_qa.baseline_tolerance > 0

    static_qa = load_qa_settings("static")
    assert static_qa.soft_ratio_threshold > 0

    benchmark = load_benchmark_settings()
    assert "silhouette.iou" in benchmark.sprite
    assert "color.mean_delta_e" in benchmark.static

    normalize_quality = load_normalize_quality_settings("sprite")
    assert 0.0 < normalize_quality.subject.min_foreground_ratio < 1.0
    assert normalize_quality.forced.stricter is not None
    assert normalize_quality.anchor.allow_recovered is False


def test_normalize_quality_unknown_mode_fails():
    with pytest.raises(ValueError, match="unknown normalize_quality mode"):
        load_normalize_quality_settings("static")


def test_normalize_quality_missing_subject_section_fails():
    from sprite_studio.gen.normalize_quality import NormalizeQualityPolicy

    with pytest.raises(ValueError, match="missing a required 'subject' section"):
        NormalizeQualityPolicy.from_dict({"anchor": {"allow_recovered": False}})


def test_normalize_quality_unknown_key_fails():
    from sprite_studio.gen.normalize_quality import NormalizeQualityPolicy

    with pytest.raises(ValueError, match="unknown keys"):
        NormalizeQualityPolicy.from_dict({
            "subject": {
                "min_foreground_ratio": 0.02,
                "min_bbox_width_ratio": 0.12,
                "min_bbox_height_ratio": 0.25,
                "max_side_edge_contact_ratio": 0.35,
                "max_key_residual_ratio": 0.35,
                "unknown_param": 1,
            },
        })


def test_unknown_section_fails():
    with pytest.raises(ValueError, match="unknown sections"):
        settings_from_dict("sprite", {"unknown_section": {}})


def test_unknown_key_fails():
    with pytest.raises(ValueError, match="unknown keys"):
        load_refine_settings("sprite")
        settings_from_dict("sprite", {
            "lattice": {"scope": "state", "max_pitch": 48, "min_pitch": 2.0, "search_half_span": 0.75, "search_step": 0.02, "confidence_floor": 0.2, "unknown_param": 123},
            "phase": {"correction": "bounded", "tolerance": 0.35, "search_step": 0.05},
            "weighting": {"mode": "continuous", "anchors": [[0.0, 1.0], [1.0, 0.1]], "coverage_threshold": 0.5},
            "color": {"metric": "oklab", "cluster_iterations": 6, "detail_bias": True, "detail_bias_share": 0.4, "detail_bias_lightness_gap": 0.25, "detail_bias_max_lightness": 0.45},
            "thin_feature": {"enabled": True, "max_thickness": 2, "coverage_relief": 0.28, "temporal_evidence": True},
            "palette": {"colors": 16, "scope": "character"},
            "fft": {"candidate_search": False, "candidates": 4, "min_prominence": 0.15},
            "dither": {"mode": "off", "strength": 1.0, "matrix": 4},
            "seam": {"check": False, "threshold": 0.08, "band": 1},
            "cleanup": {"orphan_max_area": 2, "fringe_alpha_threshold": 128},
        })


def test_invalid_override_fails():
    base = load_refine_settings("sprite")
    with pytest.raises(ValueError, match="unknown refine override"):
        apply_overrides(base, {"non_existent_key": 42})


def test_missing_required_section_fails():
    """§2.2: a mode's config must spell out every section — sprite's
    dither/seam/cleanup included, even though they're inert (off/false)."""
    with pytest.raises(ValueError, match=r"missing required section\(s\).*dither"):
        settings_from_dict("sprite", {
            "phase": {"correction": "bounded", "tolerance": 0.35, "search_step": 0.05},
        })


def test_missing_required_key_fails():
    """§2.1: one absent key inside an otherwise-present section fails loudly,
    naming the section and the missing key — never a quiet default."""
    with pytest.raises(ValueError, match=r"refine config section 'phase' missing required keys: \['search_step'\]"):
        settings_from_dict("sprite", {
            "lattice": {"scope": "state", "max_pitch": 48, "min_pitch": 2.0, "search_half_span": 0.75, "search_step": 0.02, "confidence_floor": 0.2, "coarse_to_fine": False, "large_image_pixels": 262144},
            "phase": {"correction": "bounded", "tolerance": 0.35},
            "weighting": {"mode": "continuous", "anchors": [[0.0, 1.0], [1.0, 0.1]], "coverage_threshold": 0.5},
            "color": {"metric": "oklab", "cluster_iterations": 6, "detail_bias": True, "detail_bias_share": 0.4, "detail_bias_lightness_gap": 0.25, "detail_bias_max_lightness": 0.45},
            "thin_feature": {"enabled": True, "max_thickness": 2, "coverage_relief": 0.28, "temporal_evidence": True},
            "palette": {"colors": 16, "scope": "character"},
            "fft": {"candidate_search": False, "candidates": 4, "min_prominence": 0.15},
            "dither": {"mode": "off", "strength": 1.0, "matrix": 4},
            "seam": {"check": False, "threshold": 0.08, "band": 1},
            "cleanup": {"orphan_max_area": 2, "fringe_alpha_threshold": 128},
        })


def test_full_config_round_trip_has_no_hidden_defaults():
    """Serializing committed settings back to a dict and re-loading them must
    reproduce the identical settings — the only way that can fail is a field
    quietly coming from somewhere other than the dict itself."""
    for mode in ("sprite", "static"):
        settings = load_refine_settings(mode)
        assert settings_from_dict(mode, settings.to_dict()) == settings


def test_every_tuning_field_exists_in_committed_json():
    """§2.3: no RefineSettings section field carries a code default — the
    committed JSON is the only source for a tuning value — except the one
    field explicitly marked structural-optional (dither.preset)."""
    checked = set()
    for name, cls in _SECTION_TYPES.items():
        if cls in checked:
            continue  # "lattice" and "grid" both point at LatticeSettings
        checked.add(cls)
        for item in fields(cls):
            has_default = item.default is not MISSING or item.default_factory is not MISSING  # type: ignore[misc]
            if item.metadata.get("structural_optional"):
                assert has_default, f"{cls.__name__}.{item.name} is marked structural_optional but has no default"
                continue
            assert not has_default, (
                f"{cls.__name__}.{item.name} has a code default ({item.default!r}); "
                "tuning values must be required keys sourced from committed JSON only"
            )
    # And the committed config for every mode actually supplies every one of
    # those required keys (this loads for real, exercising both the section-
    # presence and per-section key checks against the files on disk).
    for mode, required_sections in _REQUIRED_SECTIONS.items():
        settings = load_refine_settings(mode, config_dir=CONFIG_DIR)
        for section_name in required_sections:
            section_obj = getattr(settings, section_name)
            for key in _required_field_names(type(section_obj)):
                assert getattr(section_obj, key, None) is not None or key in {
                    f.name for f in fields(section_obj) if f.metadata.get("structural_optional")
                }


def test_benchmark_missing_metric_policy_section_fails(tmp_path):
    """§5: alpha_opaque_threshold / palette_retained_delta_e / texture_collapse_ratio
    must be a required, committed section — not a benchmark.json that loads
    fine without it."""
    import json

    payload = json.loads((CONFIG_DIR / "benchmark.json").read_text(encoding="utf-8"))
    del payload["metric_policy"]
    broken = tmp_path / "benchmark.json"
    broken.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="metric_policy"):
        load_benchmark_settings(config_dir=tmp_path)


def test_benchmark_metric_policy_rejects_unknown_and_missing_keys(tmp_path):
    import json

    payload = json.loads((CONFIG_DIR / "benchmark.json").read_text(encoding="utf-8"))
    payload["metric_policy"] = {"alpha_opaque_threshold": 128, "palette_retained_delta_e": 0.02}  # missing texture_collapse_ratio
    broken = tmp_path / "benchmark.json"
    broken.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="missing required keys"):
        load_benchmark_settings(config_dir=tmp_path)


def test_invalid_range_fails():
    with pytest.raises(ValueError, match="invalid pitch range"):
        settings_from_dict("sprite", {
            "lattice": {"scope": "state", "max_pitch": 2, "min_pitch": 10.0, "search_half_span": 0.75, "search_step": 0.02, "confidence_floor": 0.2, "coarse_to_fine": False, "large_image_pixels": 262144},
            "phase": {"correction": "bounded", "tolerance": 0.35, "search_step": 0.05},
            "weighting": {"mode": "continuous", "anchors": [[0.0, 1.0], [1.0, 0.1]], "coverage_threshold": 0.5},
            "color": {"metric": "oklab", "cluster_iterations": 6, "detail_bias": True, "detail_bias_share": 0.4, "detail_bias_lightness_gap": 0.25, "detail_bias_max_lightness": 0.45},
            "thin_feature": {"enabled": True, "max_thickness": 2, "coverage_relief": 0.28, "temporal_evidence": True},
            "palette": {"colors": 16, "scope": "character"},
            "fft": {"candidate_search": False, "candidates": 4, "min_prominence": 0.15},
            "dither": {"mode": "off", "strength": 1.0, "matrix": 4},
            "seam": {"check": False, "threshold": 0.08, "band": 1},
            "cleanup": {"orphan_max_area": 2, "fringe_alpha_threshold": 128},
        })
