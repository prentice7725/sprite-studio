# SPDX-License-Identifier: Apache-2.0
"""Validate and unzoom integer-upscaled logical pixel transport images.

This module deliberately does not turn an arbitrary illustration into pixel
art. It only returns a logical image when the input is sufficiently close to
an integer nearest-neighbour enlargement of an authored logical sprite.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

import numpy as np
from PIL import Image


DEFAULT_INTEGER_SCALES = (2, 3, 4, 5, 6, 8, 10, 12, 16)


@dataclass(frozen=True)
class LogicalGridResult:
    """Validation result for one transport image.

    ``logical_image`` is intentionally ``None`` on failure. A failed
    transport must not be silently promoted by a later resize operation.
    ``within_cell_variance`` is a normalized mean absolute deviation where
    zero is ideal; the other confidence scores are normalized to one as best.
    """

    pass_: bool
    logical_image: Image.Image | None
    inferred_scale_x: int | None
    inferred_scale_y: int | None
    logical_width: int | None
    logical_height: int | None
    grid_confidence: float
    within_cell_variance: float
    edge_alignment_score: float
    alpha_consistency: float
    warnings: tuple[dict[str, Any], ...]

    @property
    def passed(self) -> bool:
        """Readable alias for callers that do not want the JSON-style name."""

        return self.pass_

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly audit record without serializing pixels."""

        return {
            "pass": self.pass_,
            "inferred_scale_x": self.inferred_scale_x,
            "inferred_scale_y": self.inferred_scale_y,
            "logical_width": self.logical_width,
            "logical_height": self.logical_height,
            "grid_confidence": self.grid_confidence,
            "within_cell_variance": self.within_cell_variance,
            "edge_alignment_score": self.edge_alignment_score,
            "alpha_consistency": self.alpha_consistency,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class _Candidate:
    scale_x: int
    scale_y: int
    logical: np.ndarray
    subject_height: int
    grid_confidence: float
    within_cell_variance: float
    edge_alignment_score: float
    alpha_consistency: float


def _as_rgba_array(image: Image.Image) -> np.ndarray:
    return np.asarray(image.convert("RGBA"), dtype=np.uint8).copy()


def _chroma_mask(rgb: np.ndarray) -> np.ndarray:
    red, green, blue = (rgb[:, :, index].astype(np.int16) for index in range(3))
    return (
        (red >= 170)
        & (blue >= 170)
        & (green <= 115)
        & ((red - green) >= 70)
        & ((blue - green) >= 70)
    )


def _subject_mask(array: np.ndarray, alpha_threshold: int) -> np.ndarray:
    alpha = array[:, :, 3]
    opaque = alpha >= alpha_threshold
    if np.any(alpha < alpha_threshold):
        return opaque

    chroma = _chroma_mask(array[:, :, :3])
    if int(np.count_nonzero(chroma)) >= max(16, int(array.shape[0] * array.shape[1] * 0.005)):
        return ~chroma

    # A fully opaque image without a provable chroma background is treated as
    # subject. This is conservative: grid metrics still have to pass.
    return np.ones(alpha.shape, dtype=bool)


def _subject_height(mask: np.ndarray) -> int:
    ys = np.where(mask)[0]
    if not len(ys):
        return 0
    return int(ys.max() - ys.min() + 1)


def _edge_alignment_score(array: np.ndarray, subject: np.ndarray, scale_x: int, scale_y: int) -> float:
    horizontal = np.any(array[:, 1:] != array[:, :-1], axis=2)
    horizontal_subject = subject[:, 1:] | subject[:, :-1]
    vertical = np.any(array[1:, :] != array[:-1, :], axis=2)
    vertical_subject = subject[1:, :] | subject[:-1, :]

    total = int(np.count_nonzero(horizontal & horizontal_subject)) + int(
        np.count_nonzero(vertical & vertical_subject)
    )
    if total == 0:
        return 1.0

    aligned_horizontal = horizontal & horizontal_subject
    aligned_vertical = vertical & vertical_subject
    # A boundary between logical cells lies immediately before x/y positions
    # divisible by the inferred transport scale.
    aligned_horizontal &= (np.arange(1, array.shape[1])[None, :] % scale_x) == 0
    aligned_vertical &= (np.arange(1, array.shape[0])[:, None] % scale_y) == 0
    aligned = int(np.count_nonzero(aligned_horizontal)) + int(np.count_nonzero(aligned_vertical))
    return float(aligned / total)


def _candidate(array: np.ndarray, subject: np.ndarray, scale_x: int, scale_y: int) -> _Candidate | None:
    height, width = array.shape[:2]
    if height % scale_y or width % scale_x:
        return None

    logical_height = height // scale_y
    logical_width = width // scale_x
    cells = array.reshape(logical_height, scale_y, logical_width, scale_x, 4)
    cells = cells.transpose(0, 2, 1, 3, 4)
    representatives = cells[:, :, 0, 0, :]
    equal_to_representative = np.all(
        cells == representatives[:, :, None, None, :], axis=4
    )
    uniform_cells = equal_to_representative.all(axis=(2, 3))

    subject_cells = subject.reshape(logical_height, scale_y, logical_width, scale_x)
    subject_cells = subject_cells.transpose(0, 2, 1, 3).any(axis=(2, 3))
    focus = subject_cells
    if not np.any(focus):
        focus = np.ones_like(uniform_cells, dtype=bool)

    uniform_fraction = float(uniform_cells[focus].mean())
    focused_cells = cells[focus].astype(np.float32)
    focused_representatives = representatives[focus, None, None, :].astype(np.float32)
    deviations = np.abs(focused_cells - focused_representatives)
    within_cell_variance = float(np.mean(deviations) / 255.0)
    alpha_uniform = np.all(
        focused_cells[:, :, :, 3] == focused_representatives[:, :, :, 3], axis=(1, 2)
    )
    alpha_consistency = float(alpha_uniform.mean())
    edge_alignment = _edge_alignment_score(array, subject, scale_x, scale_y)
    confidence = float(
        0.55 * uniform_fraction
        + 0.25 * max(0.0, 1.0 - min(1.0, within_cell_variance * 8.0))
        + 0.10 * edge_alignment
        + 0.10 * alpha_consistency
    )
    logical_subject = subject.reshape(logical_height, scale_y, logical_width, scale_x)
    logical_subject = logical_subject.transpose(0, 2, 1, 3).any(axis=(2, 3))
    return _Candidate(
        scale_x=scale_x,
        scale_y=scale_y,
        logical=array[::scale_y, ::scale_x, :],
        subject_height=_subject_height(logical_subject),
        grid_confidence=confidence,
        within_cell_variance=within_cell_variance,
        edge_alignment_score=edge_alignment,
        alpha_consistency=alpha_consistency,
    )


def _candidate_key(candidate: _Candidate, target_height: int) -> tuple[int, int, float, float, int]:
    in_height_window = int(120 <= candidate.subject_height <= 136)
    height_distance = abs(candidate.subject_height - target_height)
    return (
        in_height_window,
        int(candidate.scale_x == candidate.scale_y),
        candidate.grid_confidence,
        -float(height_distance),
        candidate.scale_x + candidate.scale_y,
    )


def validate_and_unzoom(
    image: Image.Image,
    *,
    target_height: int = 128,
    alpha_threshold: int = 128,
    integer_scales: Iterable[int] = DEFAULT_INTEGER_SCALES,
) -> LogicalGridResult:
    """Validate a transport image and return an exact logical unzoom on pass.

    The validator accepts only integer cell sizes and only returns a logical
    image when all contract gates pass. It never uses LANCZOS, BOX, bilinear,
    majority-cell reconstruction, or any other geometry-changing rescue.
    """

    if target_height != 128:
        raise ValueError("the logical pixel contract currently targets 128px")
    if not 1 <= alpha_threshold <= 254:
        raise ValueError("alpha_threshold must be between 1 and 254")

    array = _as_rgba_array(image)
    subject = _subject_mask(array, alpha_threshold)
    candidates = [
        candidate
        for scale_y in integer_scales
        for scale_x in integer_scales
        if (candidate := _candidate(array, subject, int(scale_x), int(scale_y))) is not None
    ]
    if not candidates:
        return LogicalGridResult(
            pass_=False,
            logical_image=None,
            inferred_scale_x=None,
            inferred_scale_y=None,
            logical_width=None,
            logical_height=None,
            grid_confidence=0.0,
            within_cell_variance=1.0,
            edge_alignment_score=0.0,
            alpha_consistency=0.0,
            warnings=({"code": "no-integer-grid", "message": "No candidate integer transport grid fits the image dimensions."},),
        )

    best = max(candidates, key=lambda candidate: _candidate_key(candidate, target_height))
    warnings: list[dict[str, Any]] = []
    if not 120 <= best.subject_height <= 136:
        warnings.append({
            "code": "logical-subject-height-out-of-range",
            "message": f"Detected logical subject height {best.subject_height}px; expected 120–136px.",
        })
    if best.scale_x != best.scale_y:
        warnings.append({
            "code": "non-uniform-integer-grid",
            "message": f"Detected anisotropic transport scale {best.scale_x}×{best.scale_y}; expected one integer scale factor.",
        })
    if best.grid_confidence < 0.90:
        warnings.append({
            "code": "low-grid-confidence",
            "message": f"Grid confidence {best.grid_confidence:.3f} is below 0.900.",
        })
    if best.edge_alignment_score < 0.85:
        warnings.append({
            "code": "low-edge-alignment",
            "message": f"Edge alignment {best.edge_alignment_score:.3f} is below 0.850.",
        })
    if best.alpha_consistency < 0.98:
        warnings.append({
            "code": "low-alpha-consistency",
            "message": f"Alpha consistency {best.alpha_consistency:.3f} is below 0.980.",
        })

    passed = (
        120 <= best.subject_height <= 136
        and best.scale_x == best.scale_y
        and best.grid_confidence >= 0.90
        and best.edge_alignment_score >= 0.85
        and best.alpha_consistency >= 0.98
    )
    logical_image = None
    if passed:
        logical_image = Image.fromarray(best.logical, mode="RGBA")
        if logical_image.height != target_height:
            canonical_width = max(1, round(logical_image.width * target_height / logical_image.height))
            logical_image = logical_image.resize(
                (canonical_width, target_height), Image.Resampling.NEAREST
            )
    if not passed:
        warnings.append({
            "code": "FAIL_LOGICAL_GRID",
            "message": "Transport was not accepted as a validated 128-logical-pixel master; no logical image was emitted.",
        })

    return LogicalGridResult(
        pass_=passed,
        logical_image=logical_image,
        inferred_scale_x=best.scale_x,
        inferred_scale_y=best.scale_y,
            logical_width=logical_image.width if logical_image is not None else best.logical.shape[1],
            logical_height=logical_image.height if logical_image is not None else best.logical.shape[0],
        grid_confidence=round(best.grid_confidence, 6),
        within_cell_variance=round(best.within_cell_variance, 6),
        edge_alignment_score=round(best.edge_alignment_score, 6),
        alpha_consistency=round(best.alpha_consistency, 6),
        warnings=tuple(warnings),
    )


__all__ = ["DEFAULT_INTEGER_SCALES", "LogicalGridResult", "validate_and_unzoom"]
