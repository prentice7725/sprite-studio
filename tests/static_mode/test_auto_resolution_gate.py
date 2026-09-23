from __future__ import annotations

from PIL import Image, ImageDraw

from studio.static_mode.pixelize import (
    AUTO_LOGICAL_HEIGHTS,
    FeatureRegion,
    IdentityFeature,
    IdentityFeatureManifest,
    StructureExtractorOptions,
    evaluate_information_loss,
    extract_structure,
    project_auto_resolution,
    validate_logical_master,
)


def _source() -> Image.Image:
    image = Image.new("RGBA", (100, 140), (255, 0, 255, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle((20, 10, 79, 129), fill=(70, 90, 130, 255))
    draw.rectangle((20, 20, 29, 35), fill=(230, 40, 40, 255))
    return image


def _manifest() -> IdentityFeatureManifest:
    return IdentityFeatureManifest(
        source_id="R00",
        features=(
            IdentityFeature(
                id="red-mark",
                label="red asymmetric marking",
                importance="CRITICAL",
                kind="MARKING",
                region=FeatureRegion(0.20, 0.14, 0.10, 0.13),
                must_remain_on_side="LEFT",
                required_color_relation="red-dominant",
            ),
        ),
    )


def test_pse_accepts_all_auto_logical_heights() -> None:
    semantic = _source()
    for height in AUTO_LOGICAL_HEIGHTS:
        result = extract_structure(semantic, StructureExtractorOptions(target_height=height))
        assert result.image is not None
        assert result.image.height == height
        assert validate_logical_master(result.image, target_height=height).pass_


def test_critical_omission_is_hard_information_loss() -> None:
    source = _source()
    candidate = Image.new("RGBA", (64, 128), (0, 0, 0, 0))
    ImageDraw.Draw(candidate).rectangle((10, 0, 53, 127), fill=(70, 90, 130, 255))
    result = evaluate_information_loss(source, candidate, _manifest())
    assert not result.passed
    assert result.hard_failures[0]["state"] in {"OMITTED", "AMBIGUOUS"}


def test_auto_resolution_returns_minimum_passing_height_and_report() -> None:
    source = _source()
    result = project_auto_resolution(source, source, _manifest())
    assert result.passed
    assert result.selected_height == 128
    assert result.selected_image is not None
    assert result.decision_report["reason"] == "minimum_identity_preserving_height"
    assert result.decision_report["candidate_results"]["128"] == "PASS"


def test_empty_manifest_is_not_silently_accepted() -> None:
    empty = IdentityFeatureManifest(source_id="R00", features=())
    result = project_auto_resolution(_source(), _source(), empty)
    assert not result.passed
    assert result.status == "SEMANTIC_REDRAW_LOSS"
    assert result.decision_report["root_cause"] == "FEATURE_MANIFEST_ERROR"


def test_manual_resolution_override_is_reported_separately() -> None:
    result = project_auto_resolution(_source(), _source(), _manifest(), override_height=160)
    assert result.selected_height == 160
    assert result.status == "PASS_RESOLUTION_OVERRIDE"
    assert result.decision_report["resolution_override"] is True
    assert result.decision_report["reason"] == "manual_resolution_override"


def test_auto_resolution_reviews_all_valid_heights_in_one_candidate_batch() -> None:
    source = _source()
    calls: list[tuple[str, tuple[int, ...]]] = []

    def semantic_review(left, right, manifest, *, stage, **kwargs):
        calls.append((stage, ()))
        return {
            "status": "PASS_REVIEW_RESPONSE",
            "features": [{
                "id": "red-mark", "state": "PRESERVED", "confidence": 0.99,
                "reason": "red marking retained", "location": {"x": 0.0, "y": 0.08, "w": 0.2, "h": 0.16},
            }],
        }

    def candidate_review(left, images, manifest, *, stage, **kwargs):
        calls.append((stage, tuple(sorted(images))))
        return {
            height: {
                "status": "PASS_REVIEW_RESPONSE",
                "features": [{
                    "id": "red-mark", "state": "PRESERVED", "confidence": 0.99,
                    "reason": "red marking retained", "location": {"x": 0.0, "y": 0.08, "w": 0.2, "h": 0.16},
                }],
            }
            for height in images
        }

    result = project_auto_resolution(
        source, source, _manifest(), audit=True,
        identity_reviewer=semantic_review,
        identity_batch_reviewer=candidate_review,
    )
    assert result.passed
    assert result.selected_height == 128
    assert calls == [("semantic-preservation", ()), ("logical-resolution-grid", AUTO_LOGICAL_HEIGHTS)]
    assert set(result.candidate_results) == set(AUTO_LOGICAL_HEIGHTS)
