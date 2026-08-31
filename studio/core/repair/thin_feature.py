# SPDX-License-Identifier: Apache-2.0
"""Directional bridge detection for one/two-cell thin features."""

from __future__ import annotations

from collections import Counter

from PIL import Image

from .models import RepairCandidate
from .profile import RepairProfile


Coord = tuple[int, int]
_DIRECTIONS = ((1, 0), (0, 1), (1, 1), (1, -1))


class ThinFeatureAnalyzer:
    """Find a bounded transparent run between two continued one-cell lines."""

    def analyze(self, frame: Image.Image, *, frame_index: int,
                profile: RepairProfile | None = None) -> list[RepairCandidate]:
        profile = profile or RepairProfile()
        rgba = frame.convert("RGBA")
        occupied = {(x, y) for y in range(rgba.height) for x in range(rgba.width)
                    if rgba.getpixel((x, y))[3] > profile.alpha_threshold}
        candidates: list[RepairCandidate] = []
        seen: set[tuple[Coord, ...]] = set()
        for dx, dy in _DIRECTIONS:
            orthogonal = ((-dy, dx), (dy, -dx))
            for y in range(rgba.height):
                for x in range(rgba.width):
                    start = (x, y)
                    if start not in occupied:
                        continue
                    previous = (x - dx, y - dy)
                    if previous not in occupied:
                        continue
                    for gap_length in (1, 2):
                        gap = tuple((x + dx * step, y + dy * step) for step in range(1, gap_length + 1))
                        after = (x + dx * (gap_length + 1), y + dy * (gap_length + 1))
                        continued = (x + dx * (gap_length + 2), y + dy * (gap_length + 2))
                        if any(point in occupied for point in gap) or after not in occupied or continued not in occupied:
                            continue
                        if any(not (0 <= px < rgba.width and 0 <= py < rgba.height) for px, py in gap):
                            continue
                        # A thin feature has empty cross-section around the break. This
                        # keeps the rule from filling notches in broad body silhouettes.
                        cross_occupied = 0
                        for px, py in gap:
                            cross_occupied += sum((px + ox, py + oy) in occupied for ox, oy in orthogonal)
                        if cross_occupied:
                            continue
                        colors = [rgba.getpixel(point) for point in (previous, start, after, continued)]
                        color, count = Counter(colors).most_common(1)[0]
                        if color[3] <= profile.alpha_threshold:
                            continue
                        confidence = 0.98 if count == len(colors) else 0.94
                        if gap in seen:
                            continue
                        seen.add(gap)
                        candidates.append(RepairCandidate(
                            frame=frame_index, type="thin_feature_break", action="add", pixels=gap,
                            confidence=confidence, color=color,
                            details={"direction": [dx, dy], "gap_length": gap_length,
                                     "continued_cells_each_side": 2},
                        ))
        return candidates
