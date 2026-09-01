# SPDX-License-Identifier: Apache-2.0
"""Subject Validity Gate + Row-Level Acceptance Gate for Grok row normalization.

`normalize_grok_row.py` used to treat "a connected component survived cleanup"
as proof the cell held a valid sprite subject. It does not: a chroma-residue
wall, detached debris, or a narrow segmentation fragment is also "a component"
and was being fit into a cell and shipped as if it were the character.

This module is the explicit gate between "a component exists" and "the cell is
production-usable": every candidate subject is scored against a handful of
deterministic geometry/color metrics (reusing the primitives `extract.py`
already computes for `inspect_frames`, rather than re-deriving pixel logic),
and the row as a whole only PASSes when every expected subject clears the
gate. Forced segmentation (the DP fallback that manufactures N spans when
fewer than N natural subjects were found) is treated as a recovery attempt,
never as proof of success — it is scored against a stricter policy and, even
when every forced subject clears that stricter bar, the row comes back
RECOVERED_WITH_WARNING rather than a plain PASS.

See SPRITE_STUDIO_GENERATION_NORMALIZE_HARDENING_DIRECTIVE.md §2-§4.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Any

from PIL import Image

from ..frames.extract import alpha_nonzero_count, chroma_adjacent_count

RESULT_PASS = "pass"
RESULT_RECOVERED_WITH_WARNING = "recovered_with_warning"
RESULT_FAIL = "fail"

_RATIO_FIELDS = (
    "min_foreground_ratio",
    "min_bbox_width_ratio",
    "min_bbox_height_ratio",
    "max_side_edge_contact_ratio",
    "max_key_residual_ratio",
)


@dataclass(frozen=True)
class SubjectQualityPolicy:
    """Thresholds a single candidate subject cell must clear.

    All five are ratios in [0, 1], deliberately dimensionless so the same
    policy applies regardless of cell resolution (directive §14: "do not
    hardcode production thresholds").
    """

    min_foreground_ratio: float = 0.015
    min_bbox_width_ratio: float = 0.10
    min_bbox_height_ratio: float = 0.20
    max_side_edge_contact_ratio: float = 0.40
    max_key_residual_ratio: float = 0.40

    def __post_init__(self) -> None:
        for name in _RATIO_FIELDS:
            value = getattr(self, name)
            if not (0.0 <= value <= 1.0):
                raise ValueError(f"{name} must be within [0, 1], got {value}")


@dataclass(frozen=True)
class ForcedSegmentationPolicy:
    """Policy applied when the row needed forced (non-natural) segmentation."""

    require_all_subjects_valid: bool = True
    stricter: SubjectQualityPolicy | None = None


@dataclass(frozen=True)
class AnchorQualityPolicy:
    """Whether a RECOVERED_WITH_WARNING row may back a directional anchor."""

    allow_recovered: bool = False


@dataclass(frozen=True)
class NormalizeQualityPolicy:
    subject: SubjectQualityPolicy = field(default_factory=SubjectQualityPolicy)
    forced: ForcedSegmentationPolicy = field(default_factory=ForcedSegmentationPolicy)
    anchor: AnchorQualityPolicy = field(default_factory=AnchorQualityPolicy)

    @staticmethod
    def default() -> "NormalizeQualityPolicy":
        """Conservative built-in policy for standalone/CLI use without a config file.

        Studio's production path does not rely on this — it loads
        ``studio/data/config/sprite_normalize_quality.json`` and passes an
        explicit policy in (see ``studio.shared.config.load_normalize_quality_settings``).
        This default exists for the same reason ``DEFAULT_KEY_THRESHOLD`` and
        friends already exist as module constants in ``normalize_grok_row.py``:
        a documented, discoverable fallback for the bare engine tool, not a
        hidden one.
        """
        return NormalizeQualityPolicy(
            forced=ForcedSegmentationPolicy(
                require_all_subjects_valid=True,
                stricter=SubjectQualityPolicy(
                    min_foreground_ratio=0.035,
                    min_bbox_width_ratio=0.16,
                    min_bbox_height_ratio=0.32,
                    max_side_edge_contact_ratio=0.25,
                    max_key_residual_ratio=0.22,
                ),
            ),
        )

    def subject_policy_for(self, *, forced: bool) -> SubjectQualityPolicy:
        if forced and self.forced.stricter is not None:
            return self.forced.stricter
        return self.subject

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"subject": _subject_to_dict(self.subject)}
        forced: dict[str, Any] = {"require_all_subjects_valid": self.forced.require_all_subjects_valid}
        if self.forced.stricter is not None:
            forced["stricter"] = _subject_to_dict(self.forced.stricter)
        payload["forced_segmentation"] = forced
        payload["anchor"] = {"allow_recovered": self.anchor.allow_recovered}
        return payload

    @staticmethod
    def from_dict(payload: dict[str, Any]) -> "NormalizeQualityPolicy":
        """Strict parse for the on-disk config shape (directive §14). Unknown
        keys and a missing/incomplete ``subject`` section fail loudly rather
        than silently falling back to a built-in default (No Silent Fallback)."""
        known_top = {"subject", "forced_segmentation", "anchor", "kind", "mode", "version"}
        unknown = set(payload) - known_top
        if unknown:
            raise ValueError(f"normalize_quality config has unknown sections: {sorted(unknown)}")

        subject_raw = payload.get("subject")
        if not isinstance(subject_raw, dict) or not subject_raw:
            raise ValueError("normalize_quality config is missing a required 'subject' section")
        subject = _subject_from_dict(subject_raw, required=True)

        forced_raw = payload.get("forced_segmentation") or {}
        forced_unknown = set(forced_raw) - {"require_all_subjects_valid", "stricter"}
        if forced_unknown:
            raise ValueError(f"normalize_quality.forced_segmentation has unknown keys: {sorted(forced_unknown)}")
        stricter = None
        if "stricter" in forced_raw:
            stricter = _subject_from_dict(forced_raw["stricter"], required=True)
        forced = ForcedSegmentationPolicy(
            require_all_subjects_valid=bool(forced_raw.get("require_all_subjects_valid", True)),
            stricter=stricter,
        )

        anchor_raw = payload.get("anchor") or {}
        anchor_unknown = set(anchor_raw) - {"allow_recovered"}
        if anchor_unknown:
            raise ValueError(f"normalize_quality.anchor has unknown keys: {sorted(anchor_unknown)}")
        anchor = AnchorQualityPolicy(allow_recovered=bool(anchor_raw.get("allow_recovered", False)))

        return NormalizeQualityPolicy(subject=subject, forced=forced, anchor=anchor)


def _subject_to_dict(policy: SubjectQualityPolicy) -> dict[str, float]:
    return {name: getattr(policy, name) for name in _RATIO_FIELDS}


def _subject_from_dict(payload: dict[str, Any], *, required: bool) -> SubjectQualityPolicy:
    if not isinstance(payload, dict):
        raise ValueError("normalize_quality subject policy must be an object")
    known = {item.name for item in fields(SubjectQualityPolicy)}
    unknown = set(payload) - known
    if unknown:
        raise ValueError(f"normalize_quality subject policy has unknown keys: {sorted(unknown)}")
    if required:
        missing = known - set(payload)
        if missing:
            raise ValueError(f"normalize_quality subject policy is missing required keys: {sorted(missing)}")
    return SubjectQualityPolicy(**payload)


def _side_edge_alpha_count(image: Image.Image, margin: int) -> int:
    """Left+right edge contact only — a valid sprite may legitimately touch the
    bottom (feet on the ground); a full-height side wall is the suspicious shape
    (directive §2.1.C)."""
    margin = max(1, min(margin, image.width // 2 or 1))
    alpha = image.getchannel("A")
    width, height = image.size
    total = 0
    for box in ((0, 0, margin, height), (width - margin, 0, width, height)):
        total += sum(alpha.crop(box).histogram()[1:])
    return total


def evaluate_subject(
    cell: Image.Image,
    *,
    cell_width: int,
    cell_height: int,
    safe_margin_x: int,
    safe_margin_y: int,
    chroma_key: tuple[int, int, int],
    chroma_residual_threshold: float,
    edge_margin: int,
    policy: SubjectQualityPolicy,
) -> dict[str, Any]:
    """Score one already-fitted cell against ``policy``. Returns
    ``{"valid", "reasons", "metrics"}`` — always JSON-serializable so it can be
    embedded directly in the normalize report (directive §13)."""
    bbox = cell.getbbox()
    if bbox is None:
        return {
            "valid": False,
            "reasons": ["empty"],
            "metrics": {
                "foreground_ratio": 0.0,
                "bbox_width_ratio": 0.0,
                "bbox_height_ratio": 0.0,
                "edge_contact_ratio": 0.0,
                "key_residual_ratio": 0.0,
            },
        }

    foreground = alpha_nonzero_count(cell)
    usable_area = max(1, (cell_width - 2 * safe_margin_x) * (cell_height - 2 * safe_margin_y))
    foreground_ratio = foreground / usable_area

    bbox_width_ratio = (bbox[2] - bbox[0]) / cell_width
    bbox_height_ratio = (bbox[3] - bbox[1]) / cell_height

    side_edge = _side_edge_alpha_count(cell, edge_margin)
    edge_contact_ratio = side_edge / max(1, foreground)

    residual = chroma_adjacent_count(cell, chroma_key, chroma_residual_threshold)
    key_residual_ratio = residual / max(1, foreground)

    metrics = {
        "foreground_ratio": foreground_ratio,
        "bbox_width_ratio": bbox_width_ratio,
        "bbox_height_ratio": bbox_height_ratio,
        "edge_contact_ratio": edge_contact_ratio,
        "key_residual_ratio": key_residual_ratio,
    }

    reasons: list[str] = []
    if foreground_ratio < policy.min_foreground_ratio:
        reasons.append("foreground_too_small")
    if bbox_width_ratio < policy.min_bbox_width_ratio:
        reasons.append("bbox_too_narrow")
    if bbox_height_ratio < policy.min_bbox_height_ratio:
        reasons.append("bbox_too_short")
    if edge_contact_ratio > policy.max_side_edge_contact_ratio:
        reasons.append("side_edge_contact_high")
    if key_residual_ratio > policy.max_key_residual_ratio:
        reasons.append("chroma_residue_high")

    return {"valid": not reasons, "reasons": reasons, "metrics": metrics}


def resolve_row_result(valid_subjects: int, expected_subjects: int, *, forced: bool) -> str:
    """Directive §3.1: PASS only for natural segmentation with every subject
    valid; a forced row that clears the (stricter) bar is RECOVERED_WITH_WARNING,
    never a plain PASS; anything short of all-valid is FAIL."""
    if valid_subjects < expected_subjects:
        return RESULT_FAIL
    return RESULT_RECOVERED_WITH_WARNING if forced else RESULT_PASS


__all__ = [
    "RESULT_PASS",
    "RESULT_RECOVERED_WITH_WARNING",
    "RESULT_FAIL",
    "SubjectQualityPolicy",
    "ForcedSegmentationPolicy",
    "AnchorQualityPolicy",
    "NormalizeQualityPolicy",
    "evaluate_subject",
    "resolve_row_result",
]
