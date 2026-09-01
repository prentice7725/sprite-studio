# SPDX-License-Identifier: Apache-2.0
"""Test multi-metric benchmark comparison and regression gating."""

from __future__ import annotations

from studio.shared.benchmark.harness import compare_runs


def test_compare_runs_multi_metric():
    baseline = {
        "cases": [
            {
                "case": "sprite_hero",
                "mode": "sprite",
                "metrics": {
                    "silhouette": {"iou": 0.95},
                    "thin_feature": {"recovered": 0.90},
                    "color": {"mean_delta_e": 0.02},
                    "palette": {"retained": 0.98},
                    "edges": {"soft_alpha_pixels": 0},
                    "temporal": {"area_jitter": 0.01, "palette_churn": 0.02},
                },
            }
        ]
    }
    
    # Candidate with improved iou and regressed thin_feature
    candidate = {
        "cases": [
            {
                "case": "sprite_hero",
                "mode": "sprite",
                "metrics": {
                    "silhouette": {"iou": 0.98},
                    "thin_feature": {"recovered": 0.70},  # Significant regression
                    "color": {"mean_delta_e": 0.02},
                    "palette": {"retained": 0.98},
                    "edges": {"soft_alpha_pixels": 0},
                    "temporal": {"area_jitter": 0.01, "palette_churn": 0.02},
                },
            }
        ]
    }
    
    diff = compare_runs(baseline, candidate)
    assert len(diff["improvements"]) == 1
    assert diff["improvements"][0]["metric"] == "silhouette.iou"
    
    assert len(diff["regressions"]) == 1
    assert diff["regressions"][0]["metric"] == "thin_feature.recovered"
    assert diff["regressions"][0]["gate"] is True
    
    assert len(diff["gated_regressions"]) == 1
