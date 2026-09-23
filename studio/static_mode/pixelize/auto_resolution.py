# SPDX-License-Identifier: Apache-2.0
"""Auto logical-resolution selection for identity-preserving Pixel Masters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable

from PIL import Image

from .ai_cleanup import AiPixelMasterCleanupOptions, ai_pixel_master_cleanup
from .identity_manifest import IdentityFeatureManifest
from .information_loss_gate import InformationLossResult, SemanticPreservationResult, evaluate_information_loss, evaluate_semantic_preservation
from .resolution import AUTO_LOGICAL_HEIGHTS, require_logical_height
from .structure_extractor import StructureExtractorOptions, extract_structure, validate_logical_master


@dataclass(frozen=True)
class AutoResolutionResult:
    status: str
    selected_height: int | None
    selected_image: Image.Image | None
    semantic_preservation: SemanticPreservationResult
    candidate_results: dict[int, dict[str, Any]]
    decision_report: dict[str, Any]

    @property
    def passed(self) -> bool:
        return self.selected_height is not None and self.selected_image is not None and self.status == "PASS_AUTO_RESOLUTION"

    def to_dict(self) -> dict[str, Any]:
        return self.decision_report


def _candidate_label(result: InformationLossResult, validation_status: str, cleanup_mutated_dimensions: bool) -> str:
    if cleanup_mutated_dimensions:
        return "FAIL_IMPLEMENTATION_DIMENSION_MUTATION"
    if validation_status != "PASS_LOGICAL_MASTER":
        return validation_status
    return "PASS" if result.passed else result.status


def _root_cause(semantic: SemanticPreservationResult, candidate_results: dict[int, dict[str, Any]], manifest: IdentityFeatureManifest) -> str | None:
    if not manifest.features:
        return "FEATURE_MANIFEST_ERROR"
    if semantic.identity_review and semantic.identity_review.get("status") == "FAIL_REVIEW_UNAVAILABLE":
        return "IDENTITY_REVIEW_UNAVAILABLE"
    if not semantic.passed:
        return "SEMANTIC_REDRAW_LOSS"
    if not candidate_results:
        return "PSE_PROJECTION_FAILURE"
    reviews = [item.get("identity_review") for item in candidate_results.values()]
    if reviews and all(isinstance(item, dict) and item.get("status") == "FAIL_REVIEW_UNAVAILABLE" for item in reviews):
        return "IDENTITY_REVIEW_UNAVAILABLE"
    if all(item.get("validation_status") != "PASS_LOGICAL_MASTER" for item in candidate_results.values()):
        return "PSE_PROJECTION_FAILURE"
    if all(item.get("information_loss", {}).get("status") == "FAIL_INFORMATION_LOSS" for item in candidate_results.values()):
        return "SOURCE_TOO_DENSE"
    return "COMPOSITION/CROP_FAILURE"


def project_auto_resolution(
    source: Image.Image,
    semantic: Image.Image,
    manifest: IdentityFeatureManifest,
    *,
    candidates: Iterable[int] = AUTO_LOGICAL_HEIGHTS,
    palette_size: int | None = 48,
    alpha_threshold: int = 128,
    opaque_coverage_threshold: float = 0.18,
    audit: bool = False,
    override_height: int | None = None,
    identity_reviewer: Callable[..., dict[str, Any]] | None = None,
) -> AutoResolutionResult:
    heights = tuple(require_logical_height(int(value), field_name="candidate height") for value in candidates)
    if override_height is not None:
        override_height = require_logical_height(override_height, field_name="override_height")
        heights = (override_height,)
    if len(set(heights)) != len(heights):
        raise ValueError("candidate heights must be unique")
    semantic_review = identity_reviewer(source, semantic, manifest, stage="semantic-preservation") if identity_reviewer else None
    semantic_gate = evaluate_semantic_preservation(source, semantic, manifest, identity_review=semantic_review)
    candidate_results: dict[int, dict[str, Any]] = {}
    selected_height: int | None = None
    selected_image: Image.Image | None = None

    if semantic_gate.passed:
        for height in heights:
            extracted = extract_structure(
                semantic,
                StructureExtractorOptions(
                    target_height=height,
                    palette_size=palette_size,
                    alpha_threshold=alpha_threshold,
                    opaque_coverage_threshold=opaque_coverage_threshold,
                ),
            )
            if extracted.image is None:
                candidate_results[height] = {
                    "status": extracted.report.get("status", "FAIL_PSE"),
                    "validation_status": "FAIL_PSE",
                    "identity_loss_index": None,
                    "information_loss": None,
                    "pse": extracted.report,
                    "logical_validation": None,
                    "cleanup_mutated_dimensions": False,
                }
                continue
            before_size = extracted.image.size
            cleanup = ai_pixel_master_cleanup(
                extracted.image,
                AiPixelMasterCleanupOptions(
                    target_size=height,
                    palette_size=None,
                    alpha_threshold=alpha_threshold,
                    geometry_resize=False,
                    remove_background=False,
                    remove_isolated_area=0,
                ),
            )
            cleanup_mutated_dimensions = cleanup.image.size != before_size
            validation = validate_logical_master(
                cleanup.image,
                target_height=height,
                alpha_threshold=alpha_threshold,
                max_palette_size=palette_size,
            )
            validation_metrics = dict(validation.metrics)
            validation_metrics["cleanup_mutated_dimensions"] = cleanup_mutated_dimensions
            identity_review = identity_reviewer(source, cleanup.image, manifest, stage=f"logical-{height}") if identity_reviewer else None
            information_loss = evaluate_information_loss(source, cleanup.image, manifest, identity_review=identity_review)
            status = _candidate_label(information_loss, validation.status, cleanup_mutated_dimensions)
            candidate_results[height] = {
                "status": status,
                "validation_status": validation.status,
                "identity_loss_index": information_loss.identity_loss_index,
                "information_loss": information_loss.to_dict(),
                "pse": extracted.report,
                "cleanup": cleanup.report,
                "logical_validation": {**validation.to_dict(), "metrics": validation_metrics},
                "cleanup_mutated_dimensions": cleanup_mutated_dimensions,
                "identity_review": identity_review,
            }
            structurally_valid = validation.status == "PASS_LOGICAL_MASTER" and not cleanup_mutated_dimensions
            if selected_height is None and (status == "PASS" or (override_height == height and structurally_valid)):
                selected_height = height
                selected_image = cleanup.image
                if override_height == height:
                    break
                if not audit:
                    break

    root_cause = _root_cause(semantic_gate, candidate_results, manifest) if selected_height is None else None
    if selected_height is not None and override_height is not None:
        status = "PASS_RESOLUTION_OVERRIDE"
    else:
        override_result = candidate_results.get(override_height, {}) if override_height is not None else {}
        if override_height is not None and (
            override_result.get("validation_status") != "PASS_LOGICAL_MASTER"
            or override_result.get("cleanup_mutated_dimensions")
        ):
            status = "FAIL_OVERRIDE_LOGICAL_VALIDATION"
        else:
            if selected_height is not None:
                status = "PASS_AUTO_RESOLUTION"
            elif root_cause == "IDENTITY_REVIEW_UNAVAILABLE":
                status = "IDENTITY_REVIEW_UNAVAILABLE"
            else:
                status = "SEMANTIC_REDRAW_LOSS" if not semantic_gate.passed else "NO_VALID_RESOLUTION"
    candidate_report = {
        str(height): ("PASS" if item["status"] == "PASS" else item["status"])
        for height, item in candidate_results.items()
    }
    for height in heights:
        candidate_report.setdefault(str(height), "NOT_REQUIRED")
    decision_report = {
        "mode": "AUDIT" if audit else "AUTO",
        "candidates": list(heights),
        "selected": selected_height,
        "reason": "manual_resolution_override" if override_height is not None else ("minimum_identity_preserving_height" if selected_height is not None else "no_valid_resolution"),
        "candidate_results": candidate_report,
        "candidate_details": {str(height): item for height, item in candidate_results.items()},
        "identity_loss_index": {
            str(height): item["identity_loss_index"]
            for height, item in candidate_results.items()
            if item.get("identity_loss_index") is not None
        },
        "semantic_preservation": semantic_gate.to_dict(),
        "root_cause": root_cause,
        "identity_review_method": "codex-multimodal-ifm-review" if identity_reviewer else "pixel-proxy-only",
        "identity_gate_authoritative": identity_reviewer is not None,
        "resize_rescue": False,
        "threshold_relaxation": False,
        "palette_relaxation": False,
        "resolution_override": override_height is not None,
        "identity_gate_passed": bool(selected_height is not None and candidate_results.get(selected_height, {}).get("status") == "PASS"),
    }
    return AutoResolutionResult(status, selected_height, selected_image, semantic_gate, candidate_results, decision_report)


__all__ = ["AutoResolutionResult", "project_auto_resolution"]
