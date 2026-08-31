# SPDX-License-Identifier: Apache-2.0
"""Temporal majority repair with bounded local motion search."""

from __future__ import annotations

from collections import Counter

from PIL import Image

from .models import RepairCandidate
from .profile import RepairProfile


Coord = tuple[int, int]
_CARDINAL = ((-1, 0), (1, 0), (0, -1), (0, 1))


def _mask(frame: Image.Image, threshold: int) -> set[Coord]:
    rgba = frame.convert("RGBA")
    return {(x, y) for y in range(rgba.height) for x in range(rgba.width) if rgba.getpixel((x, y))[3] > threshold}


def _best_shift(source: set[Coord], target: set[Coord], radius: int) -> tuple[int, int]:
    best = (0, 0)
    best_overlap = -1
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            overlap = sum((x + dx, y + dy) in target for x, y in source)
            if overlap > best_overlap or (overlap == best_overlap and abs(dx) + abs(dy) < abs(best[0]) + abs(best[1])):
                best = (dx, dy)
                best_overlap = overlap
    return best


class TemporalRepairEngine:
    def analyze(self, previous_frame: Image.Image, current_frame: Image.Image, next_frame: Image.Image,
                *, frame_index: int, state: str, profile: RepairProfile | None = None) -> list[RepairCandidate]:
        profile = profile or RepairProfile()
        previous = previous_frame.convert("RGBA")
        current = current_frame.convert("RGBA")
        following = next_frame.convert("RGBA")
        if previous.size != current.size or following.size != current.size:
            raise ValueError("temporal repair requires equal-sized logical frames")
        previous_mask = _mask(previous, profile.alpha_threshold)
        current_mask = _mask(current, profile.alpha_threshold)
        next_mask = _mask(following, profile.alpha_threshold)
        prev_shift = _best_shift(previous_mask, current_mask, profile.temporal_search_radius)
        next_shift = _best_shift(next_mask, current_mask, profile.temporal_search_radius)
        mapped_previous = {(x + prev_shift[0], y + prev_shift[1]) for x, y in previous_mask}
        mapped_next = {(x + next_shift[0], y + next_shift[1]) for x, y in next_mask}
        missing = mapped_previous & mapped_next - current_mask
        low_confidence_state = any(state.endswith(suffix) for suffix in ("_attack", "_hit", "_down"))
        result: list[RepairCandidate] = []
        for x, y in sorted(missing):
            if not (0 <= x < current.width and 0 <= y < current.height):
                continue
            neighbor_count = sum((x + dx, y + dy) in current_mask for dx, dy in _CARDINAL)
            if neighbor_count < 2:
                continue
            prev_source = (x - prev_shift[0], y - prev_shift[1])
            next_source = (x - next_shift[0], y - next_shift[1])
            colors = [previous.getpixel(prev_source), following.getpixel(next_source)]
            if colors[0] != colors[1]:
                continue
            color = Counter(colors).most_common(1)[0][0]
            if color[3] <= profile.alpha_threshold:
                continue
            symmetric_motion = abs(prev_shift[0] + next_shift[0]) + abs(prev_shift[1] + next_shift[1]) <= 1
            confidence = 0.72 if low_confidence_state else 0.98 if symmetric_motion else 0.90
            result.append(RepairCandidate(
                frame=frame_index, type="temporal_missing_pixel", action="add", pixels=((x, y),),
                confidence=confidence, color=color, engine="temporal",
                details={"previous_shift": list(prev_shift), "next_shift": list(next_shift),
                         "current_neighbors": neighbor_count, "state_aware": True,
                         "symmetric_motion": symmetric_motion},
            ))
        return result
