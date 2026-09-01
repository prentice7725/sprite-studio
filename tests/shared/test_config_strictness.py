# SPDX-License-Identifier: Apache-2.0
"""Test strict validation of configuration files across Refine, QA, and Benchmark."""

from __future__ import annotations

import pytest

from studio.shared.config import (
    apply_overrides,
    load_benchmark_settings,
    load_qa_settings,
    load_refine_settings,
    settings_from_dict,
)


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


def test_invalid_range_fails():
    with pytest.raises(ValueError, match="invalid pitch range"):
        settings_from_dict("sprite", {
            "lattice": {"scope": "state", "max_pitch": 2, "min_pitch": 10.0, "search_half_span": 0.75, "search_step": 0.02, "confidence_floor": 0.2},
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
