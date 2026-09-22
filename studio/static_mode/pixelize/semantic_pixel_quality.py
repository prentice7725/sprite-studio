# SPDX-License-Identifier: Apache-2.0
"""Quality gate for semantic AI pixel-art sources before PSE projection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from PIL import Image

from .structure_extractor import remove_background


@dataclass(frozen=True)
class SemanticPixelQualityResult:
    status: str
    metrics: dict[str, Any]
    warnings: tuple[dict[str, Any], ...]

    @property
    def passed(self) -> bool:
        return self.status in {"PASS_SEMANTIC_SOURCE", "WARN_PAINTERLY"}

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, "metrics": self.metrics, "warnings": list(self.warnings)}


def _bbox(alpha: np.ndarray, threshold: int) -> tuple[int, int, int, int] | None:
    ys, xs = np.where(alpha >= threshold)
    if not len(xs):
        return None
    return int(xs.min()), int(ys.min()), int(xs.max() + 1), int(ys.max() + 1)


def _adjacent_transition_ratio(rgb: np.ndarray, alpha: np.ndarray, threshold: int) -> float:
    opaque = alpha >= threshold
    horizontal = opaque[:, 1:] & opaque[:, :-1]
    vertical = opaque[1:, :] & opaque[:-1, :]
    h_total = int(np.count_nonzero(horizontal))
    v_total = int(np.count_nonzero(vertical))
    h_changed = int(np.count_nonzero(np.any(rgb[:, 1:] != rgb[:, :-1], axis=2) & horizontal))
    v_changed = int(np.count_nonzero(np.any(rgb[1:, :] != rgb[:-1, :], axis=2) & vertical))
    return (h_changed + v_changed) / max(1, h_total + v_total)


def _cluster_metrics(rgb: np.ndarray, alpha: np.ndarray, threshold: int) -> dict[str, float | int]:
    opaque = alpha >= threshold
    if not np.any(opaque):
        return {"opaque_pixels": 0, "opaque_color_count": 0, "color_ratio": 0.0, "median_quantized_cluster": 0.0, "small_quantized_cluster_fraction": 0.0}
    quantized = (rgb[opaque] // 16).astype(np.uint8)
    _, counts = np.unique(quantized, axis=0, return_counts=True)
    return {
        "opaque_pixels": int(np.count_nonzero(opaque)),
        "opaque_color_count": int(len(np.unique(rgb[opaque], axis=0))),
        "color_ratio": round(float(len(np.unique(rgb[opaque], axis=0)) / max(1, np.count_nonzero(opaque))), 6),
        "median_quantized_cluster": round(float(np.median(counts)), 3),
        "small_quantized_cluster_fraction": round(float(np.count_nonzero(counts <= 4) / max(1, len(counts))), 6),
    }


def evaluate_semantic_source(
    image: Image.Image,
    *,
    alpha_threshold: int = 128,
    background_tolerance: float = 28.0,
) -> SemanticPixelQualityResult:
    """Measure semantic simplification without claiming logical-grid validity."""

    background_removed, background_mode, background_stats = remove_background(
        image, tolerance=background_tolerance
    )
    array = np.asarray(background_removed.convert("RGBA"), dtype=np.uint8)
    alpha = array[:, :, 3]
    bbox = _bbox(alpha, alpha_threshold)
    cluster = _cluster_metrics(array[:, :, :3], alpha, alpha_threshold)
    fringe = (alpha > 0) & (alpha < 255)
    fringe_ratio = float(np.count_nonzero(fringe) / max(1, np.count_nonzero(alpha > 0)))
    transition_ratio = _adjacent_transition_ratio(array[:, :, :3], alpha, alpha_threshold)
    subject_area_ratio = 0.0 if bbox is None else ((bbox[2] - bbox[0]) * (bbox[3] - bbox[1])) / (image.width * image.height)

    warnings: list[dict[str, Any]] = []
    if bbox is None:
        warnings.append({"code": "FAIL_SUBJECT", "message": "No subject remains after background handling."})
    if background_mode == "none":
        warnings.append({"code": "FAIL_BACKGROUND", "message": "No removable or transparent background was proven."})
    painterly = fringe_ratio > 0.08 or float(cluster["color_ratio"]) > 0.12
    if painterly:
        warnings.append({"code": "WARN_PAINTERLY", "message": "Semantic source retains unusually soft or color-rich detail."})
    severely_unabstracted = fringe_ratio > 0.35 and float(cluster["color_ratio"]) > 0.25 and transition_ratio > 0.8
    if severely_unabstracted:
        warnings.append({"code": "FAIL_NOT_ABSTRACTED", "message": "Source still resembles a high-frequency painterly illustration."})

    if bbox is None:
        status = "FAIL_SUBJECT"
    elif background_mode == "none":
        status = "FAIL_BACKGROUND"
    elif severely_unabstracted:
        status = "FAIL_NOT_ABSTRACTED"
    elif painterly:
        status = "WARN_PAINTERLY"
    else:
        status = "PASS_SEMANTIC_SOURCE"
    metrics = {
        "input_size": list(image.size),
        "background": {"mode": background_mode, **background_stats},
        "subject_bbox": list(bbox) if bbox else None,
        "subject_area_ratio": round(subject_area_ratio, 6),
        "edge_softness_ratio": round(fringe_ratio, 6),
        "adjacent_transition_ratio": round(transition_ratio, 6),
        "cluster_size_distribution": cluster,
    }
    return SemanticPixelQualityResult(status, metrics, tuple(warnings))


__all__ = ["SemanticPixelQualityResult", "evaluate_semantic_source"]
