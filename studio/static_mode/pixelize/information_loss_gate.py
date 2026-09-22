# SPDX-License-Identifier: Apache-2.0
"""Deterministic identity-preservation and information-loss gates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import numpy as np
from PIL import Image

from .identity_manifest import IdentityFeature, IdentityFeatureManifest
from .structure_extractor import remove_background


FeatureState = Literal["PRESERVED", "SIMPLIFIED", "MERGED", "OMITTED", "AMBIGUOUS"]
STATE_SCORE: dict[FeatureState, float] = {
    "PRESERVED": 1.0,
    "SIMPLIFIED": 0.85,
    "AMBIGUOUS": 0.50,
    "MERGED": 0.25,
    "OMITTED": 0.0,
}
IMPORTANCE_WEIGHT = {"CRITICAL": 4, "IMPORTANT": 2, "OPTIONAL": 1}


@dataclass(frozen=True)
class SemanticPreservationResult:
    passed: bool
    status: str
    feature_results: tuple[dict[str, Any], ...]
    topology_warnings: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "pass": self.passed,
            "status": self.status,
            "feature_results": list(self.feature_results),
            "topology_warnings": list(self.topology_warnings),
        }


@dataclass(frozen=True)
class InformationLossResult:
    passed: bool
    status: str
    identity_loss_index: float
    retention: float
    feature_results: tuple[dict[str, Any], ...]
    hard_failures: tuple[dict[str, Any], ...]
    pixel_evidence: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "pass": self.passed,
            "status": self.status,
            "identity_loss_index": self.identity_loss_index,
            "retention": self.retention,
            "feature_results": list(self.feature_results),
            "hard_failures": list(self.hard_failures),
            "pixel_evidence": self.pixel_evidence,
        }


def _alpha_bbox(array: np.ndarray, threshold: int) -> tuple[int, int, int, int] | None:
    ys, xs = np.where(array[:, :, 3] >= threshold)
    if not len(xs):
        return None
    return int(xs.min()), int(ys.min()), int(xs.max() + 1), int(ys.max() + 1)


def _subject_view(image: Image.Image, threshold: int = 128) -> tuple[np.ndarray, tuple[int, int, int, int] | None]:
    cleaned, _, _ = remove_background(image, tolerance=28.0)
    array = np.asarray(cleaned.convert("RGBA"), dtype=np.uint8)
    return array, _alpha_bbox(array, threshold)


def _project_region(feature: IdentityFeature, source_bbox: tuple[int, int, int, int] | None, source_size: tuple[int, int], target_size: tuple[int, int]) -> tuple[int, int, int, int] | None:
    if feature.region is None or source_bbox is None:
        return None
    left, top, right, bottom = source_bbox
    width = max(1, right - left)
    height = max(1, bottom - top)
    source_width, source_height = source_size
    region = feature.region
    # IFM coordinates are source-canvas normalized; convert them to subject-local
    # normalized coordinates before mapping to a cropped logical candidate.
    x0 = (region.x * source_width - left) / width
    y0 = (region.y * source_height - top) / height
    x1 = ((region.x + region.w) * source_width - left) / width
    y1 = ((region.y + region.h) * source_height - top) / height
    x0, y0, x1, y1 = [max(0.0, min(1.0, value)) for value in (x0, y0, x1, y1)]
    target_width, target_height = target_size
    px0 = int(np.floor(x0 * target_width))
    py0 = int(np.floor(y0 * target_height))
    px1 = max(px0 + 1, int(np.ceil(x1 * target_width)))
    py1 = max(py0 + 1, int(np.ceil(y1 * target_height)))
    return max(0, min(target_width - 1, px0)), max(0, min(target_height - 1, py0)), min(target_width, px1), min(target_height, py1)


def _source_region(feature: IdentityFeature, source_bbox: tuple[int, int, int, int] | None, source_size: tuple[int, int]) -> tuple[int, int, int, int] | None:
    if feature.region is None:
        return None
    width, height = source_size
    region = feature.region
    return (
        int(np.floor(region.x * width)),
        int(np.floor(region.y * height)),
        max(1, int(np.ceil((region.x + region.w) * width))),
        max(1, int(np.ceil((region.y + region.h) * height))),
    )


def _region_evidence(array: np.ndarray, region: tuple[int, int, int, int] | None, threshold: int = 128) -> dict[str, Any]:
    if region is None:
        return {"available": False, "visible_ratio": 0.0, "bbox": None, "width": 0, "height": 0, "min_dimension": 0}
    x0, y0, x1, y1 = region
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(array.shape[1], max(x0 + 1, x1)), min(array.shape[0], max(y0 + 1, y1))
    mask = array[y0:y1, x0:x1, 3] >= threshold
    if not np.any(mask):
        return {"available": True, "visible_ratio": 0.0, "bbox": None, "width": 0, "height": 0, "min_dimension": 0, "mean_rgb": None}
    ys, xs = np.where(mask)
    width = int(xs.max() - xs.min() + 1)
    height = int(ys.max() - ys.min() + 1)
    return {
        "available": True,
        "visible_ratio": round(float(np.count_nonzero(mask) / max(1, mask.size)), 6),
        "bbox": [int(x0 + xs.min()), int(y0 + ys.min()), int(x0 + xs.max() + 1), int(y0 + ys.max() + 1)],
        "width": width,
        "height": height,
        "min_dimension": min(width, height),
        "mean_rgb": [round(float(value), 3) for value in np.mean(array[y0:y1, x0:x1, :3][mask], axis=0)],
    }


def _color_relation_matches(mean_rgb: list[float] | None, relation: str | None) -> bool:
    if mean_rgb is None or not relation:
        return True
    relation = relation.lower()
    red, green, blue = mean_rgb
    if "red" in relation:
        return red >= green + 25 and red >= blue + 25
    if "green" in relation:
        return green >= red + 25 and green >= blue + 25
    if "blue" in relation:
        return blue >= red + 25 and blue >= green + 25
    if "yellow" in relation:
        return red >= 120 and green >= 100 and abs(red - green) <= 90 and blue + 35 < min(red, green)
    if "white" in relation:
        return min(red, green, blue) >= 170
    if "black" in relation:
        return max(red, green, blue) <= 90
    if "brown" in relation:
        return red > blue + 20 and green > blue + 5 and red < 190
    return True


def _rect_gap(a: list[int] | None, b: list[int] | None) -> int | None:
    if not a or not b:
        return None
    horizontal = max(0, max(a[0], b[0]) - min(a[2], b[2]))
    vertical = max(0, max(a[1], b[1]) - min(a[3], b[3]))
    if horizontal == 0 and vertical == 0:
        return 0
    return max(horizontal, vertical)


def _feature_state(feature: IdentityFeature, source: np.ndarray, source_bbox: tuple[int, int, int, int] | None, candidate: np.ndarray, candidate_bbox: tuple[int, int, int, int] | None) -> dict[str, Any]:
    if feature.region is None or source_bbox is None or candidate_bbox is None:
        return {"id": feature.id, "label": feature.label, "importance": feature.importance, "state": "AMBIGUOUS", "reason": "feature-region-or-subject-bbox-missing", "source": {}, "candidate": {}}
    candidate_left, candidate_top, candidate_right, candidate_bottom = candidate_bbox
    candidate = candidate[candidate_top:candidate_bottom, candidate_left:candidate_right]
    candidate_bbox = (0, 0, candidate.shape[1], candidate.shape[0])
    source_region = _source_region(feature, source_bbox, (source.shape[1], source.shape[0]))
    candidate_region = _project_region(feature, source_bbox, (source.shape[1], source.shape[0]), (candidate.shape[1], candidate.shape[0]))
    source_evidence = _region_evidence(source, source_region)
    candidate_evidence = _region_evidence(candidate, candidate_region)
    if source_evidence["visible_ratio"] <= 0.0:
        state: FeatureState = "AMBIGUOUS"
        reason = "manifest-region-does-not-overlap-source-subject"
    elif candidate_evidence["visible_ratio"] <= 0.0:
        state = "OMITTED"
        reason = "no-visible-projection"
    elif feature.must_remain_on_side:
        center_x = (candidate_evidence["bbox"][0] + candidate_evidence["bbox"][2]) / 2 / max(1, candidate.shape[1])
        wrong_side = (feature.must_remain_on_side == "LEFT" and center_x >= 0.5) or (feature.must_remain_on_side == "RIGHT" and center_x <= 0.5)
        if wrong_side:
            state = "AMBIGUOUS"
            reason = "critical-side-relation-changed"
        else:
            state = "PRESERVED" if candidate_evidence["visible_ratio"] >= source_evidence["visible_ratio"] * 0.45 else "SIMPLIFIED"
            reason = "visible-and-side-preserved"
    else:
        state = "PRESERVED" if candidate_evidence["visible_ratio"] >= source_evidence["visible_ratio"] * 0.45 else "SIMPLIFIED"
        reason = "visible-projection"
    if state not in {"OMITTED", "AMBIGUOUS"} and not _color_relation_matches(candidate_evidence.get("mean_rgb"), feature.required_color_relation):
        state = "AMBIGUOUS"
        reason = "required-color-relation-not-preserved"
    return {
        "id": feature.id,
        "label": feature.label,
        "importance": feature.importance,
        "kind": feature.kind,
        "state": state,
        "reason": reason,
        "source": source_evidence,
        "candidate": candidate_evidence,
        "must_remain_separated_from": list(feature.must_remain_separated_from),
        "required_color_relation": feature.required_color_relation,
    }


def _apply_separation_states(manifest: IdentityFeatureManifest, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {item["id"]: item for item in results}
    for feature in manifest.features:
        current = by_id[feature.id]
        for other_id in feature.must_remain_separated_from:
            other = by_id.get(other_id)
            if other is None:
                continue
            gap = _rect_gap(current.get("candidate", {}).get("bbox"), other.get("candidate", {}).get("bbox"))
            current.setdefault("pixel_evidence", {})[f"separation_to:{other_id}"] = gap
            if gap is not None and gap < 1 and current["state"] not in {"OMITTED", "AMBIGUOUS"}:
                current["state"] = "MERGED"
                current["reason"] = f"merged-with:{other_id}"
    return results


def evaluate_information_loss(source: Image.Image, candidate: Image.Image, manifest: IdentityFeatureManifest) -> InformationLossResult:
    source_array, source_bbox = _subject_view(source)
    candidate_array, candidate_bbox = _subject_view(candidate)
    results = [_feature_state(feature, source_array, source_bbox, candidate_array, candidate_bbox) for feature in manifest.features]
    results = _apply_separation_states(manifest, results)
    total_weight = sum(IMPORTANCE_WEIGHT[item["importance"]] for item in results)
    retained = sum(IMPORTANCE_WEIGHT[item["importance"]] * STATE_SCORE[item["state"]] for item in results)
    retention = retained / max(1, total_weight)
    ili = 1.0 - retention
    hard_failures = [
        {"feature_id": item["id"], "label": item["label"], "state": item["state"], "reason": item["reason"]}
        for item in results
        if item["importance"] == "CRITICAL" and item["state"] in {"MERGED", "OMITTED", "AMBIGUOUS"}
    ]
    pixel_evidence: dict[str, Any] = {"features": {}}
    for item in results:
        evidence = item.get("candidate", {})
        pixel_evidence["features"][item["id"]] = {
            "projected_width": evidence.get("width", 0),
            "projected_height": evidence.get("height", 0),
            "min_visible_dimension": evidence.get("min_dimension", 0),
            "risk": evidence.get("min_dimension", 0) < 2,
            **item.get("pixel_evidence", {}),
        }
    passed = not hard_failures and round(ili, 6) <= 0.15
    status = "PASS_INFORMATION_PRESERVATION" if passed else "FAIL_INFORMATION_LOSS"
    if not manifest.features:
        passed = False
        status = "FAIL_FEATURE_MANIFEST_EMPTY"
    return InformationLossResult(passed, status, round(ili, 6), round(retention, 6), tuple(results), tuple(hard_failures), pixel_evidence)


def evaluate_semantic_preservation(source: Image.Image, semantic: Image.Image, manifest: IdentityFeatureManifest) -> SemanticPreservationResult:
    result = evaluate_information_loss(source, semantic, manifest)
    topology = tuple(
        {"feature_id": item["feature_id"], "reason": item["reason"]}
        for item in result.hard_failures
        if "side" in item["reason"] or "merged" in item["reason"]
    )
    passed = not result.hard_failures and bool(manifest.features)
    status = "PASS_SEMANTIC_PRESERVATION" if passed else "FAIL_SEMANTIC_PRESERVATION"
    return SemanticPreservationResult(passed, status, result.feature_results, topology)


__all__ = [
    "FeatureState",
    "InformationLossResult",
    "SemanticPreservationResult",
    "evaluate_information_loss",
    "evaluate_semantic_preservation",
]
