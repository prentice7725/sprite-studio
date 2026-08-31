# SPDX-License-Identifier: MIT
"""Heuristic animation QA for refined frame sets.

The checks are intentionally diagnostic: they never silently alter frames and
they label geometry-based heuristics as warnings so an operator can accept or
reroll with context.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import mean, pstdev
from typing import Any

from PIL import Image, ImageChops


@dataclass(frozen=True)
class AnimationQaResult:
    state: str
    ok: bool
    metrics: dict[str, Any]
    warnings: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "sprite-studio-animation-qa",
            "state": self.state,
            "ok": self.ok,
            "metrics": self.metrics,
            "warnings": list(self.warnings),
        }


def _bbox(frame: Image.Image) -> tuple[int, int, int, int] | None:
    return frame.convert("RGBA").getchannel("A").getbbox()


def _relative(values: list[float]) -> float:
    if not values or min(values) <= 0:
        return 0.0
    return max(values) / mean(values) - 1.0


def analyze_animation(frames: list[Image.Image], state: str, *, baseline_tolerance: float = 1.5,
                      scale_jump_ratio: float = 0.20, duplicate_threshold: int = 2) -> AnimationQaResult:
    if not frames:
        return AnimationQaResult(state, False, {"frame_count": 0}, ({"code": "MISSING_FRAMES", "message": "No frames are available for animation QA."},))
    boxes = [_bbox(frame) for frame in frames]
    valid = [box for box in boxes if box is not None]
    if len(valid) != len(frames):
        return AnimationQaResult(state, False, {"frame_count": len(frames), "nonempty_frames": len(valid)}, ({"code": "EMPTY_FRAME", "message": "An empty frame cannot be evaluated as an animation."},))
    widths = [box[2] - box[0] for box in valid]
    heights = [box[3] - box[1] for box in valid]
    bottoms = [box[3] for box in valid]
    center_x = frames[0].width / 2.0
    side_balance: list[int] = []
    for frame in frames:
        alpha = frame.convert("RGBA").getchannel("A")
        left = sum(1 for y in range(frame.height) for x in range(frame.width // 2) if alpha.getpixel((x, y)) > 16)
        right = sum(1 for y in range(frame.height) for x in range(frame.width // 2, frame.width) if alpha.getpixel((x, y)) > 16)
        side_balance.append(1 if right - left > 3 else -1 if left - right > 3 else 0)
    pair_differences = []
    duplicates = []
    for index, (left, right) in enumerate(zip(frames, frames[1:]), start=1):
        difference = ImageChops.difference(left.convert("RGBA"), right.convert("RGBA"))
        changed = sum(1 for pixel in difference.getdata() if pixel[3] > duplicate_threshold)
        pair_differences.append(changed)
        if changed == 0:
            duplicates.append(index - 1)
    warnings: list[dict[str, Any]] = []
    baseline_sigma = pstdev(bottoms) if len(bottoms) > 1 else 0.0
    if baseline_sigma > baseline_tolerance:
        warnings.append({"code": "BASELINE_JITTER", "message": f"baseline jitter is {baseline_sigma:.2f}px (>{baseline_tolerance:.2f}px)"})
    scale_jump = max(_relative([float(value) for value in widths]), _relative([float(value) for value in heights]))
    if scale_jump > scale_jump_ratio:
        warnings.append({"code": "SCALE_JUMP", "message": f"frame content scale changes by {scale_jump:.1%} across the row"})
    if duplicates:
        warnings.append({"code": "DUPLICATE_FRAME", "message": f"adjacent frames are identical at indices {duplicates}"})
    if state.endswith("_attack") and _relative([float(value) for value in widths]) > scale_jump_ratio:
        warnings.append({"code": "WEAPON_LENGTH_JUMP", "message": "attack silhouette extent changes abruptly; inspect weapon length/pose continuity"})
    nonzero = [value for value in side_balance if value]
    flips = sum(1 for left, right in zip(nonzero, nonzero[1:]) if left != right)
    if state.endswith("_attack") and flips >= 2:
        warnings.append({"code": "HANDEDNESS_FLIP", "message": "left/right silhouette mass alternates repeatedly; inspect weapon hand continuity"})
    metrics = {
        "frame_count": len(frames),
        "baseline": {"values": bottoms, "sigma": round(baseline_sigma, 4)},
        "content": {"widths": widths, "heights": heights, "scale_jump": round(scale_jump, 4)},
        "pair_changed_pixels": pair_differences,
        "duplicate_indices": duplicates,
        "side_balance": side_balance,
        "handedness_flip_transitions": flips,
        "pivot": {"x": 0.5, "y": round((frames[0].height - 1) / frames[0].height, 6)},
    }
    return AnimationQaResult(state, True, metrics, tuple(warnings))
