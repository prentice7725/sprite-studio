# SPDX-License-Identifier: Apache-2.0
"""Auto logical-resolution selection for identity-preserving Pixel Masters."""

from __future__ import annotations

from dataclasses import dataclass, field
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
    candidate_images: dict[int, Image.Image] = field(default_factory=dict)

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
    identity_batch_reviewer: Callable[..., dict[int, dict[str, Any]]] | None = None,
    review_workdir: Path | None = None,
) -> AutoResolutionResult:
    heights = tuple(require_logical_height(int(value), field_name="candidate height") for value in candidates)
    if override_height is not None:
        override_height = require_logical_height(override_height, field_name="override_height")
        heights = (override_height,)
    if len(set(heights)) != len(heights):
        raise ValueError("candidate heights must be unique")
    def review_pair(left: Image.Image, right: Image.Image, stage: str) -> dict[str, Any] | None:
        if identity_reviewer is None:
            return None
        if review_workdir is None:
            return identity_reviewer(left, right, manifest, stage=stage)
        return identity_reviewer(left, right, manifest, stage=stage, workdir=review_workdir)

    semantic_review = review_pair(source, semantic, "semantic-preservation")
    semantic_gate = evaluate_semantic_preservation(source, semantic, manifest, identity_review=semantic_review)
    candidate_results: dict[int, dict[str, Any]] = {}
    candidate_images: dict[int, Image.Image] = {}
    selected_height: int | None = None
    selected_image: Image.Image | None = None

    if semantic_gate.passed:
        prepared_candidates: dict[int, dict[str, Any]] = {}
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
            if validation.status == "PASS_LOGICAL_MASTER" and not cleanup_mutated_dimensions:
                candidate_images[height] = cleanup.image.copy()
            prepared_candidates[height] = {
                "image": cleanup.image,
                "extracted": extracted,
                "cleanup": cleanup,
                "validation": validation,
                "validation_metrics": validation_metrics,
                "cleanup_mutated_dimensions": cleanup_mutated_dimensions,
            }

        batch_reviews: dict[int, dict[str, Any]] = {}
        if identity_batch_reviewer is not None and candidate_images:
            try:
                if review_workdir is None:
                    batch_reviews = identity_batch_reviewer(
                        source, candidate_images, manifest, stage="logical-resolution-grid"
                    )
                else:
                    batch_reviews = identity_batch_reviewer(
                        source, candidate_images, manifest,
                        stage="logical-resolution-grid", workdir=review_workdir,
                    )
            except Exception as exc:
                batch_reviews = {}
                review_error = f"{type(exc).__name__}: {exc}"[:2000]
                for height in candidate_images:
                    batch_reviews[height] = {
                        "status": "FAIL_REVIEW_UNAVAILABLE",
                        "error": review_error,
                        "features": [
                            {"id": feature.id, "state": "AMBIGUOUS", "confidence": 0.0,
                             "reason": "identity-review-unavailable", "location": None}
                            for feature in manifest.features
                        ],
                    }

        for height, prepared in prepared_candidates.items():
            image = prepared["image"]
            if height in batch_reviews:
                identity_review = batch_reviews[height]
            else:
                identity_review = review_pair(source, image, f"logical-{height}")
            information_loss = evaluate_information_loss(source, image, manifest, identity_review=identity_review)
            validation = prepared["validation"]
            cleanup_mutated_dimensions = prepared["cleanup_mutated_dimensions"]
            status = _candidate_label(information_loss, validation.status, cleanup_mutated_dimensions)
            candidate_results[height] = {
                "status": status,
                "validation_status": validation.status,
                "identity_loss_index": information_loss.identity_loss_index,
                "information_loss": information_loss.to_dict(),
                "pse": prepared["extracted"].report,
                "cleanup": prepared["cleanup"].report,
                "logical_validation": {**validation.to_dict(), "metrics": prepared["validation_metrics"]},
                "cleanup_mutated_dimensions": cleanup_mutated_dimensions,
                "identity_review": identity_review,
            }
            structurally_valid = validation.status == "PASS_LOGICAL_MASTER" and not cleanup_mutated_dimensions
            if selected_height is None and (status == "PASS" or (override_height == height and structurally_valid)):
                selected_height = height
                selected_image = image

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
        "identity_review_method": "codex-multimodal-ifm-review" if (identity_reviewer or identity_batch_reviewer) else "pixel-proxy-only",
        "identity_gate_authoritative": identity_reviewer is not None,
        "resize_rescue": False,
        "threshold_relaxation": False,
        "palette_relaxation": False,
        "resolution_override": override_height is not None,
        "identity_gate_passed": bool(selected_height is not None and candidate_results.get(selected_height, {}).get("status") == "PASS"),
    }
    return AutoResolutionResult(status, selected_height, selected_image, semantic_gate, candidate_results, decision_report, candidate_images)


__all__ = ["AutoResolutionResult", "project_auto_resolution"]
