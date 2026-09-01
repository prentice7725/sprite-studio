# SPDX-License-Identifier: Apache-2.0
"""Benchmark metrics (spec §9.4, §9.5).

What "better" means, written down. Sprite Mode and Static Mode are graded on
different things — silhouette and temporal stability versus palette retention
and seam integrity — but every metric here answers the same shape of question:
how far is the recovered asset from the ground truth we degraded?

All colour distances are Oklab, for the reason Shared Core exists at all: a
benchmark scored in RGB would reward a refine pass that the rest of the
pipeline considers wrong.
"""

from __future__ import annotations

from typing import Any, Sequence

import numpy as np
from PIL import Image

from studio.shared.color.oklab import rgb_to_oklab
from studio.shared.config import MetricPolicySettings
from studio.shared.palette import opaque_colors


def _policy(policy: MetricPolicySettings | None) -> MetricPolicySettings:
    """Resolve the metric policy the same way every other settings object in
    this codebase resolves an optional override — an explicit instance if the
    caller has one, else the committed config (§5's SSOT), never a bare
    numeric literal at the call site."""
    if policy is not None:
        return policy
    from studio.shared.config import load_benchmark_settings

    return load_benchmark_settings().metric_policy


def _aligned(truth: Image.Image, result: Image.Image) -> tuple[np.ndarray, np.ndarray]:
    """Compare at the ground truth's size; a size mismatch is itself a failure.

    Nearest-neighbour, never smooth: resampling the result with interpolation
    would hide exactly the softness the benchmark is trying to measure.
    """
    reference = np.asarray(truth.convert("RGBA"), dtype=np.uint8)
    candidate = result.convert("RGBA")
    if candidate.size != truth.size:
        candidate = candidate.resize(truth.size, Image.Resampling.NEAREST)
    return reference, np.asarray(candidate, dtype=np.uint8)


def silhouette_accuracy(truth: Image.Image, result: Image.Image, *, policy: MetricPolicySettings | None = None) -> dict[str, Any]:
    """Alpha-mask IoU — did the shape survive?"""
    threshold = _policy(policy).alpha_opaque_threshold
    reference, candidate = _aligned(truth, result)
    a = reference[:, :, 3] >= threshold
    b = candidate[:, :, 3] >= threshold
    union = np.count_nonzero(a | b)
    intersection = np.count_nonzero(a & b)
    return {
        "iou": round(intersection / union, 6) if union else 1.0,
        "missing_pixels": int(np.count_nonzero(a & ~b)),
        "extra_pixels": int(np.count_nonzero(b & ~a)),
    }


def color_accuracy(truth: Image.Image, result: Image.Image, *, policy: MetricPolicySettings | None = None) -> dict[str, Any]:
    """Mean/max Oklab error over pixels both images agree are opaque."""
    threshold = _policy(policy).alpha_opaque_threshold
    reference, candidate = _aligned(truth, result)
    both = (reference[:, :, 3] >= threshold) & (candidate[:, :, 3] >= threshold)
    if not both.any():
        return {"mean_delta_e": None, "max_delta_e": None, "compared_pixels": 0}
    delta = np.sqrt(
        np.sum((rgb_to_oklab(reference[both][:, :3]) - rgb_to_oklab(candidate[both][:, :3])) ** 2, axis=-1)
    )
    return {
        "mean_delta_e": round(float(delta.mean()), 6),
        "max_delta_e": round(float(delta.max()), 6),
        "compared_pixels": int(both.sum()),
    }


def palette_accuracy(truth: Image.Image, result: Image.Image, *, policy: MetricPolicySettings | None = None) -> dict[str, Any]:
    """How much of the original palette survived, and how much was invented."""
    retained_delta_e = _policy(policy).palette_retained_delta_e
    truth_colors, _ = opaque_colors([truth])
    result_colors, _ = opaque_colors([result])
    if truth_colors.shape[0] == 0:
        return {"truth_colors": 0, "result_colors": int(result_colors.shape[0]), "retained": None}
    truth_lab = rgb_to_oklab(truth_colors)
    if result_colors.shape[0] == 0:
        return {"truth_colors": int(truth_colors.shape[0]), "result_colors": 0, "retained": 0.0}
    result_lab = rgb_to_oklab(result_colors)
    distances = np.sqrt(np.sum((truth_lab[:, None, :] - result_lab[None, :, :]) ** 2, axis=2))
    # A colour counts as retained if something within `retained_delta_e` Oklab
    # exists in the result — below that threshold the difference is not
    # visible, so demanding byte equality would punish a harmless rounding.
    retained = float(np.count_nonzero(distances.min(axis=1) <= retained_delta_e)) / truth_colors.shape[0]
    return {
        "truth_colors": int(truth_colors.shape[0]),
        "result_colors": int(result_colors.shape[0]),
        "retained": round(retained, 6),
    }


def thin_feature_recovery(truth: Image.Image, result: Image.Image, *, policy: MetricPolicySettings | None = None) -> dict[str, Any]:
    """Survival rate of pixels that are thin in the ground truth."""
    threshold = _policy(policy).alpha_opaque_threshold
    reference, candidate = _aligned(truth, result)
    opaque = reference[:, :, 3] >= threshold
    neighbours = (
        np.roll(opaque, 1, 0).astype(int) + np.roll(opaque, -1, 0).astype(int)
        + np.roll(opaque, 1, 1).astype(int) + np.roll(opaque, -1, 1).astype(int)
    )
    thin = opaque & (neighbours <= 2)
    if not thin.any():
        return {"thin_pixels": 0, "recovered": None}
    kept = thin & (candidate[:, :, 3] >= threshold)
    return {
        "thin_pixels": int(thin.sum()),
        "recovered": round(float(kept.sum()) / float(thin.sum()), 6),
    }


def edge_cleanliness(result: Image.Image) -> dict[str, Any]:
    alpha = np.asarray(result.convert("RGBA"), dtype=np.uint8)[:, :, 3]
    soft = int(np.count_nonzero((alpha > 0) & (alpha < 255)))
    return {"soft_alpha_pixels": soft, "clean": soft == 0}


def texture_collapse(truth: Image.Image, result: Image.Image, *, policy: MetricPolicySettings | None = None) -> dict[str, Any]:
    """Did flat-area detail get flattened away entirely? (spec §9.5)"""
    collapse_ratio = _policy(policy).texture_collapse_ratio
    reference, candidate = _aligned(truth, result)
    truth_unique = np.unique(reference[:, :, :3].reshape(-1, 3), axis=0).shape[0]
    result_unique = np.unique(candidate[:, :, :3].reshape(-1, 3), axis=0).shape[0]
    ratio = result_unique / truth_unique if truth_unique else 1.0
    return {
        "truth_colors": int(truth_unique),
        "result_colors": int(result_unique),
        "retention_ratio": round(float(ratio), 6),
        "collapsed": bool(ratio < collapse_ratio),
    }


def temporal_consistency(frames: Sequence[Image.Image], *, policy: MetricPolicySettings | None = None) -> dict[str, Any]:
    """Frame-to-frame stability of the recovered row (spec §9.4).

    Two signals, because they fail independently: the silhouette's area can be
    steady while the palette flickers, and vice versa.
    """
    threshold = _policy(policy).alpha_opaque_threshold
    if len(frames) < 2:
        return {"frames": len(frames), "area_jitter": None, "palette_churn": None}
    areas: list[int] = []
    palettes: list[set[tuple[int, int, int]]] = []
    for frame in frames:
        array = np.asarray(frame.convert("RGBA"), dtype=np.uint8)
        opaque = array[:, :, 3] >= threshold
        areas.append(int(opaque.sum()))
        colors = np.unique(array[opaque][:, :3], axis=0) if opaque.any() else np.zeros((0, 3), dtype=np.uint8)
        palettes.append({tuple(int(value) for value in color) for color in colors})
    mean_area = float(np.mean(areas)) or 1.0
    churn = [
        len(palettes[index] ^ palettes[index - 1]) / max(1, len(palettes[index] | palettes[index - 1]))
        for index in range(1, len(palettes))
    ]
    return {
        "frames": len(frames),
        "area_jitter": round(float(np.std(areas)) / mean_area, 6),
        "palette_churn": round(float(np.mean(churn)), 6),
    }


def seam_integrity(result: Image.Image) -> dict[str, Any]:
    """Wrap-edge continuity of a tile, in Oklab (spec §9.5)."""
    array = np.asarray(result.convert("RGBA"), dtype=np.uint8)
    if array.shape[0] < 2 or array.shape[1] < 2:
        return {"horizontal_delta_e": None, "vertical_delta_e": None}
    left, right = rgb_to_oklab(array[:, 0, :3]), rgb_to_oklab(array[:, -1, :3])
    top, bottom = rgb_to_oklab(array[0, :, :3]), rgb_to_oklab(array[-1, :, :3])
    return {
        "horizontal_delta_e": round(float(np.mean(np.sqrt(np.sum((right - left) ** 2, axis=-1)))), 6),
        "vertical_delta_e": round(float(np.mean(np.sqrt(np.sum((bottom - top) ** 2, axis=-1)))), 6),
    }


def sprite_metrics(truth: Image.Image, result: Image.Image, *, policy: MetricPolicySettings | None = None) -> dict[str, Any]:
    resolved = _policy(policy)
    return {
        "silhouette": silhouette_accuracy(truth, result, policy=resolved),
        "color": color_accuracy(truth, result, policy=resolved),
        "palette": palette_accuracy(truth, result, policy=resolved),
        "thin_feature": thin_feature_recovery(truth, result, policy=resolved),
        "edges": edge_cleanliness(result),
    }


def static_metrics(truth: Image.Image, result: Image.Image, *, policy: MetricPolicySettings | None = None) -> dict[str, Any]:
    resolved = _policy(policy)
    return {
        "color": color_accuracy(truth, result, policy=resolved),
        "palette": palette_accuracy(truth, result, policy=resolved),
        "edges": edge_cleanliness(result),
        "texture": texture_collapse(truth, result, policy=resolved),
        "seam": seam_integrity(result),
    }
