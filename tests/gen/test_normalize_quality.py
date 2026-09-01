# SPDX-License-Identifier: Apache-2.0
"""Subject Validity Gate + Row-Level Acceptance Gate.

Covers `SPRITE_STUDIO_GENERATION_NORMALIZE_HARDENING_DIRECTIVE.md` §16-17:
malformed rows must FAIL instead of being promoted, and a clean row must
still PASS. The malformed fixture below is synthetic (the real regression
image, ``20a93ecb-d4c5-48d1-9c4d-125dd5171325.png``, is not committed to this
repo) but reproduces the same pathology the directive describes: three cells
dominated by chroma residue / fragmented debris / a narrow edge strip, and
exactly one cell holding a real subject.
"""

from __future__ import annotations

import pytest
from PIL import Image, ImageDraw

from sprite_studio.gen.normalize_grok_row import normalize_image
from sprite_studio.gen.normalize_quality import (
    AnchorQualityPolicy,
    ForcedSegmentationPolicy,
    NormalizeQualityPolicy,
    SubjectQualityPolicy,
    evaluate_subject,
    resolve_row_result,
)

MAGENTA = (255, 0, 255)
GREEN = (0, 255, 0)


def _solid_cell(size: tuple[int, int], color: tuple[int, int, int], box: tuple[int, int, int, int]) -> Image.Image:
    cell = Image.new("RGBA", size, (0, 0, 0, 0))
    ImageDraw.Draw(cell).rectangle(box, fill=(*color, 255))
    return cell


# --- evaluate_subject: unit-level metric behavior ---------------------------

def test_valid_subject_passes_default_policy():
    cell = _solid_cell((64, 64), (220, 40, 40), (10, 6, 54, 60))
    result = evaluate_subject(
        cell, cell_width=64, cell_height=64, safe_margin_x=4, safe_margin_y=4,
        chroma_key=GREEN, chroma_residual_threshold=180.0, edge_margin=4,
        policy=SubjectQualityPolicy(),
    )
    assert result["valid"] is True
    assert result["reasons"] == []


def test_empty_cell_is_rejected():
    cell = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    result = evaluate_subject(
        cell, cell_width=64, cell_height=64, safe_margin_x=4, safe_margin_y=4,
        chroma_key=GREEN, chroma_residual_threshold=180.0, edge_margin=4,
        policy=SubjectQualityPolicy(),
    )
    assert result["valid"] is False
    assert result["reasons"] == ["empty"]


def test_extreme_narrow_fragment_is_rejected():
    """Directive §16 Case H: a sliver survives component cleanup but is not a subject."""
    cell = _solid_cell((64, 64), (220, 40, 40), (30, 4, 33, 60))
    result = evaluate_subject(
        cell, cell_width=64, cell_height=64, safe_margin_x=4, safe_margin_y=4,
        chroma_key=GREEN, chroma_residual_threshold=180.0, edge_margin=4,
        policy=SubjectQualityPolicy(),
    )
    assert result["valid"] is False
    assert "bbox_too_narrow" in result["reasons"]


def test_chroma_wall_is_rejected():
    """Directive §16 Case B: a large connected component that is mostly key-family residue."""
    residue = (200, 90, 190)  # distance ~124 from magenta key -- inside the fringe band
    cell = _solid_cell((64, 64), residue, (4, 4, 60, 60))
    result = evaluate_subject(
        cell, cell_width=64, cell_height=64, safe_margin_x=4, safe_margin_y=4,
        chroma_key=MAGENTA, chroma_residual_threshold=180.0, edge_margin=4,
        policy=SubjectQualityPolicy(),
    )
    assert result["valid"] is False
    assert "chroma_residue_high" in result["reasons"]


def test_side_wall_strip_is_rejected_on_edge_contact():
    cell = _solid_cell((64, 64), (220, 40, 40), (0, 0, 6, 64))
    result = evaluate_subject(
        cell, cell_width=64, cell_height=64, safe_margin_x=4, safe_margin_y=4,
        chroma_key=GREEN, chroma_residual_threshold=180.0, edge_margin=6,
        policy=SubjectQualityPolicy(max_side_edge_contact_ratio=0.10),
    )
    assert result["valid"] is False
    assert "side_edge_contact_high" in result["reasons"]


def test_bottom_contact_alone_is_not_penalized():
    """Directive §2.1.C: a valid sprite may legitimately touch the bottom (feet)."""
    cell = _solid_cell((64, 64), (220, 40, 40), (10, 0, 54, 64))
    result = evaluate_subject(
        cell, cell_width=64, cell_height=64, safe_margin_x=4, safe_margin_y=4,
        chroma_key=GREEN, chroma_residual_threshold=180.0, edge_margin=4,
        policy=SubjectQualityPolicy(),
    )
    assert "side_edge_contact_high" not in result["reasons"]


# --- resolve_row_result: row-level acceptance state --------------------------

def test_row_result_states():
    assert resolve_row_result(4, 4, forced=False) == "pass"
    assert resolve_row_result(4, 4, forced=True) == "recovered_with_warning"
    assert resolve_row_result(1, 4, forced=False) == "fail"
    assert resolve_row_result(1, 4, forced=True) == "fail"


# --- NormalizeQualityPolicy: strict config parsing ----------------------------

def test_policy_from_dict_round_trips():
    policy = NormalizeQualityPolicy(
        subject=SubjectQualityPolicy(min_foreground_ratio=0.03),
        forced=ForcedSegmentationPolicy(stricter=SubjectQualityPolicy(min_foreground_ratio=0.05)),
        anchor=AnchorQualityPolicy(allow_recovered=True),
    )
    restored = NormalizeQualityPolicy.from_dict(policy.to_dict())
    assert restored.subject.min_foreground_ratio == 0.03
    assert restored.forced.stricter.min_foreground_ratio == 0.05
    assert restored.anchor.allow_recovered is True


def test_policy_from_dict_rejects_unknown_top_level_section():
    with pytest.raises(ValueError, match="unknown sections"):
        NormalizeQualityPolicy.from_dict({"subject": {}, "bogus": {}})


def test_policy_out_of_range_ratio_rejected():
    with pytest.raises(ValueError, match="within \\[0, 1\\]"):
        SubjectQualityPolicy(min_foreground_ratio=1.5)


# --- End-to-end regression fixture: the directive's observed pathology -------

def _malformed_row() -> Image.Image:
    """Reproduces the directive's real-world regression: expected 4 subjects,
    3 cells are chroma-residue / fragmented debris / a narrow residue strip,
    1 cell is a real subject."""
    residue_a = (200, 90, 190)
    residue_b = (150, 90, 150)
    image = Image.new("RGB", (640, 180), MAGENTA)
    draw = ImageDraw.Draw(image)
    # cell 0: chroma-residue wall dominating the region
    draw.rectangle((35, 20, 35 + 82, 160), fill=residue_a)
    # cell 1: fragmented debris -- scattered tiny blobs, none of them a subject
    draw.rectangle((185 + 30, 60, 185 + 40, 70), fill=(60, 180, 90))
    draw.rectangle((185 + 55, 90, 185 + 62, 96), fill=(60, 180, 90))
    draw.rectangle((185 + 10, 120, 185 + 16, 126), fill=(60, 180, 90))
    # cell 2: one valid subject (body + head)
    left = 335
    draw.rectangle((left, 28, left + 82, 155), fill=(220, 40, 40))
    draw.rectangle((left + 24, 10, left + 58, 45), fill=(220, 40, 40))
    # cell 3: narrow residue strip hugging the edge
    left = 485
    draw.rectangle((left + 70, 10, left + 78, 170), fill=residue_b)
    return image


def test_malformed_row_regression_fixture_fails_normalize():
    output, report = normalize_image(
        _malformed_row(), MAGENTA, count=4, cell_width=64, cell_height=64,
        safe_margin_x=4, safe_margin_y=4,
    )

    # The malformed strip is still produced for inspection (directive §7) --
    # normalize never destroys evidence, it just must not claim success.
    assert output.size == (256, 64)

    assert report["result"] == "fail"
    assert report["expected_subjects"] == 4
    assert report["valid_subjects"] < 4
    assert len(report["subjects"]) == 4

    invalid = {s["index"]: s["reasons"] for s in report["subjects"] if not s["valid"]}
    valid = {s["index"] for s in report["subjects"] if s["valid"]}
    # This must not become "structurally 4 valid cells" (directive §1's core defect):
    # component existence in every span is not equivalent to subject validity.
    assert 2 in valid
    assert invalid  # at least the residue/fragment/strip cells were caught
    assert len(invalid) >= 2


def test_clean_four_subject_row_still_passes():
    """Guards against the gate over-tightening: a normal, well-formed row must
    still come back PASS, not a false rejection."""
    image = Image.new("RGB", (640, 180), GREEN)
    draw = ImageDraw.Draw(image)
    for index, color in enumerate(((220, 40, 40), (40, 80, 220), (220, 180, 30), (150, 50, 190))):
        left = 35 + index * 150
        draw.rectangle((left, 28, left + 82, 155), fill=color)
        draw.rectangle((left + 24, 10, left + 58, 45), fill=color)

    _output, report = normalize_image(
        image, GREEN, count=4, cell_width=64, cell_height=64, safe_margin_x=4, safe_margin_y=4,
    )
    assert report["result"] == "pass"
    assert report["valid_subjects"] == 4
    assert report["segmentation"]["forced"] is False
