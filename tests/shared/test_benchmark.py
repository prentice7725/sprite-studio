# SPDX-License-Identifier: Apache-2.0
"""Synthetic degradation benchmark contracts (spec §9).

The benchmark is the gate the spec puts in front of algorithm changes (§16.10),
so its own properties matter: it has to be deterministic, it has to actually
degrade, and its comparison has to surface a per-case regression that an
improved average would otherwise hide.
"""

from __future__ import annotations

import json

import numpy as np
import pytest
from PIL import Image

from studio.shared.benchmark import (
    BenchmarkCase,
    compare_runs,
    default_cases,
    degrade,
    run_benchmark,
    run_case,
    synthetic_scene,
    synthetic_sprite_row,
)
from studio.shared.benchmark.degrade import DEGRADATIONS
from studio.shared.benchmark.harness import upscale
from studio.shared.benchmark.metrics import silhouette_accuracy, temporal_consistency


def test_every_degradation_actually_degrades_the_asset_it_models() -> None:
    """A no-op degradation scores a perfect recovery while testing nothing.

    Regression: ``thin_feature_loss`` used a fixed neighbour-count rule and so
    damaged nothing in a 6x-upscaled sprite (a six-pixel-wide blade has four
    opaque neighbours), and ``chroma_contamination`` damaged nothing in a
    full-bleed scene (no alpha edge anywhere). Both reported flawless scores.
    """
    sprite = upscale(synthetic_sprite_row(frames=1)[0], 6)
    scene = upscale(synthetic_scene(size=16), 6)
    for name in DEGRADATIONS:
        # Thin-feature loss models a *sprite* failure; the rest apply to both.
        source = sprite if name == "thin_feature_loss" else scene
        damaged = degrade(source, [name])
        assert damaged.size == source.size
        assert not np.array_equal(np.asarray(damaged), np.asarray(source)), f"{name} changed nothing"


def test_thin_feature_loss_leaves_a_scene_without_thin_features_alone() -> None:
    """The flip side: it must not invent damage where the failure cannot occur."""
    scene = upscale(synthetic_scene(size=16), 6)
    assert np.array_equal(np.asarray(degrade(scene, ["thin_feature_loss"])), np.asarray(scene))


def test_degradation_is_deterministic_for_a_seed() -> None:
    source = upscale(synthetic_sprite_row(frames=1)[0], 6)
    first = degrade(source, ["thin_feature_loss"], seed=99)
    second = degrade(source, ["thin_feature_loss"], seed=99)
    assert np.array_equal(np.asarray(first), np.asarray(second))
    different = degrade(source, ["thin_feature_loss"], seed=100)
    assert not np.array_equal(np.asarray(first), np.asarray(different))


def test_unknown_degradation_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown degradation"):
        degrade(synthetic_scene(size=8), ["sharpen"])


def test_sprite_refine_recovers_a_subpixel_offset_row() -> None:
    """§9.3's headline case: art that sits between grid lines must still snap back."""
    case = BenchmarkCase("sprite:offset", "sprite", tuple(synthetic_sprite_row()), ("subpixel_offset",))
    result = run_case(case)
    assert result.metrics["silhouette"]["iou"] > 0.9
    assert result.metrics["thin_feature"]["recovered"] > 0.8


def test_static_refine_survives_boundary_bleed() -> None:
    case = BenchmarkCase("static:bleed", "static", (synthetic_scene(),), ("boundary_bleed",))
    result = run_case(case)
    assert result.metrics["color"]["mean_delta_e"] < 0.05
    assert result.metrics["palette"]["retained"] > 0.8


def test_temporal_consistency_separates_a_stable_row_from_a_flickering_one() -> None:
    stable = synthetic_sprite_row(frames=4)
    steady = temporal_consistency(stable)
    # A row whose frames differ wildly in area must score worse jitter.
    shrinking = [frame.crop((0, 0, frame.width - index * 4, frame.height)).resize(frame.size, Image.Resampling.NEAREST)
                 for index, frame in enumerate(stable)]
    noisy = temporal_consistency(shrinking)
    assert steady["area_jitter"] is not None and noisy["area_jitter"] is not None
    assert steady["area_jitter"] <= noisy["area_jitter"]


def test_silhouette_metric_notices_a_missing_limb() -> None:
    truth = synthetic_sprite_row(frames=1)[0]
    damaged = truth.copy()
    damaged.paste((0, 0, 0, 0), (0, 0, truth.width, 6))
    assert silhouette_accuracy(truth, damaged)["iou"] < 1.0
    assert silhouette_accuracy(truth, truth)["iou"] == 1.0


def test_default_suite_runs_and_summarises_both_modes() -> None:
    report = run_benchmark(default_cases()[:4])
    payload = report.to_dict()
    assert payload["kind"] == "asset-studio-benchmark"
    assert len(payload["cases"]) == 4
    assert payload["summary"]["cases"] == 4
    assert json.dumps(payload)  # the record has to be serialisable to be a baseline


def test_benchmark_report_writes_a_baseline_file(tmp_path) -> None:
    report = run_benchmark(default_cases()[:2])
    path = report.write(tmp_path / "benchmark" / "baseline.json")
    assert path.is_file()
    assert json.loads(path.read_text(encoding="utf-8"))["kind"] == "asset-studio-benchmark"


def test_compare_runs_names_a_regression_instead_of_averaging_it_away() -> None:
    """An algorithm change that lifts the mean while breaking cases is a regression."""
    baseline = {
        "cases": [
            {"case": "sprite:a", "mode": "sprite", "metrics": {"silhouette": {"iou": 0.90}}},
            {"case": "sprite:b", "mode": "sprite", "metrics": {"silhouette": {"iou": 0.90}}},
            {"case": "static:c", "mode": "static", "metrics": {"color": {"mean_delta_e": 0.02}}},
        ]
    }
    candidate = {
        "cases": [
            {"case": "sprite:a", "mode": "sprite", "metrics": {"silhouette": {"iou": 0.99}}},
            {"case": "sprite:b", "mode": "sprite", "metrics": {"silhouette": {"iou": 0.70}}},
            {"case": "static:c", "mode": "static", "metrics": {"color": {"mean_delta_e": 0.05}}},
        ]
    }
    diff = compare_runs(baseline, candidate)
    regressed = {item["case"] for item in diff["regressions"]}
    improved = {item["case"] for item in diff["improvements"]}
    assert regressed == {"sprite:b", "static:c"}
    assert improved == {"sprite:a"}


def test_compare_runs_reports_added_and_removed_cases() -> None:
    diff = compare_runs(
        {"cases": [{"case": "old", "mode": "sprite", "metrics": {"silhouette": {"iou": 1.0}}}]},
        {"cases": [{"case": "new", "mode": "sprite", "metrics": {"silhouette": {"iou": 1.0}}}]},
    )
    changes = {item["case"]: item["change"] for item in diff["moved"]}
    assert changes == {"old": "removed", "new": "added"}


def test_the_committed_baseline_still_reproduces() -> None:
    """The baseline is only a gate while the pipeline still reproduces it.

    A drift here means either an intentional algorithm change (record a new
    baseline in the same commit) or an accidental one (the point of the gate).
    """
    from pathlib import Path

    from studio.shared.benchmark import default_cases

    baseline_path = Path(__file__).resolve().parents[2] / "studio" / "data" / "benchmark" / "baseline.json"
    assert baseline_path.is_file(), "committed benchmark baseline is missing"
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    current = run_benchmark(default_cases()).to_dict()
    diff = compare_runs(baseline, current)
    assert diff["regressions"] == [], f"benchmark regressed against the committed baseline: {diff['regressions']}"
    assert diff["improvements"] == [], (
        "benchmark improved against the committed baseline; record a new one in the same commit: "
        f"{diff['improvements']}"
    )
