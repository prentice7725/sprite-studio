# SPDX-License-Identifier: Apache-2.0
"""Deterministic local defect detection on logical-pixel frames."""

from __future__ import annotations

from collections import Counter, deque
from typing import Iterable

from PIL import Image

from .models import RepairCandidate
from .profile import RepairProfile


Coord = tuple[int, int]
_CARDINAL = ((-1, 0), (1, 0), (0, -1), (0, 1))


def _opaque(image: Image.Image, profile: RepairProfile) -> set[Coord]:
    rgba = image.convert("RGBA")
    return {(x, y) for y in range(rgba.height) for x in range(rgba.width)
            if rgba.getpixel((x, y))[3] > profile.alpha_threshold}


def _components(points: set[Coord], width: int, height: int) -> list[set[Coord]]:
    remaining = set(points)
    result: list[set[Coord]] = []
    while remaining:
        start = remaining.pop()
        component = {start}
        queue = deque((start,))
        while queue:
            x, y = queue.popleft()
            for dx, dy in _CARDINAL:
                point = (x + dx, y + dy)
                if 0 <= point[0] < width and 0 <= point[1] < height and point in remaining:
                    remaining.remove(point)
                    component.add(point)
                    queue.append(point)
        result.append(component)
    return result


def _brightness(color: tuple[int, int, int, int]) -> float:
    return 0.2126 * color[0] + 0.7152 * color[1] + 0.0722 * color[2]


def _dominant(colors: Iterable[tuple[int, int, int, int]]) -> tuple[int, int, int, int] | None:
    values = [color for color in colors if color[3] > 0]
    return Counter(values).most_common(1)[0][0] if values else None


class RepairAnalyzer:
    """Detect holes, one-cell outline gaps and disconnected stray pixels."""

    def analyze(self, frame: Image.Image, *, frame_index: int = 0,
                profile: RepairProfile | None = None) -> list[RepairCandidate]:
        profile = profile or RepairProfile()
        rgba = frame.convert("RGBA")
        occupied = _opaque(rgba, profile)
        if not occupied:
            return []
        xs = [point[0] for point in occupied]
        ys = [point[1] for point in occupied]
        bbox = (min(xs), min(ys), max(xs) + 1, max(ys) + 1)
        candidates: list[RepairCandidate] = []
        hole_pixels: set[Coord] = set()

        transparent = {(x, y) for y in range(rgba.height) for x in range(rgba.width) if (x, y) not in occupied}
        for component in _components(transparent, rgba.width, rgba.height):
            if len(component) > profile.max_hole_pixels:
                continue
            if any(x in {0, rgba.width - 1} or y in {0, rgba.height - 1} for x, y in component):
                continue
            colors = []
            for x, y in component:
                for dx, dy in _CARDINAL:
                    point = (x + dx, y + dy)
                    if point in occupied:
                        colors.append(rgba.getpixel(point))
            protected = any(self._protected(point, bbox, profile) for point in component)
            same_four = len(component) == 1 and len(colors) == 4 and len(set(colors)) == 1
            confidence = 0.98 if same_four else 0.82
            if protected:
                confidence = min(confidence, 0.69)
            color = _dominant(colors)
            if color is not None:
                pixels = tuple(sorted(component))
                hole_pixels.update(component)
                candidates.append(RepairCandidate(
                    frame=frame_index, type="small_hole", action="add", pixels=pixels,
                    confidence=confidence, color=color, protected=protected,
                    details={"size": len(component), "same_four_neighbors": same_four},
                ))

        palette = Counter(rgba.get_flattened_data())
        visible_colors = [color for color in palette if color[3] > profile.alpha_threshold]
        dark_cutoff = (sorted(_brightness(color) for color in visible_colors)[max(0, len(visible_colors) // 3 - 1)]
                       if len(visible_colors) >= 2 else -1)
        for y in range(1, rgba.height - 1):
            for x in range(1, rgba.width - 1):
                point = (x, y)
                if point in occupied or point in hole_pixels:
                    continue
                pairs = [((x - 1, y), (x + 1, y), "horizontal"), ((x, y - 1), (x, y + 1), "vertical")]
                for left, right, direction in pairs:
                    if left not in occupied or right not in occupied:
                        continue
                    colors = (rgba.getpixel(left), rgba.getpixel(right))
                    if any(_brightness(color) > dark_cutoff for color in colors):
                        continue
                    protected = self._protected(point, bbox, profile)
                    if direction == "horizontal":
                        extended = ((x - 2, y), (x + 2, y))
                    else:
                        extended = ((x, y - 2), (x, y + 2))
                    strong_continuation = colors[0] == colors[1] and all(
                        endpoint in occupied and rgba.getpixel(endpoint) == colors[0] for endpoint in extended
                    )
                    confidence = 0.99 if strong_continuation else 0.94
                    if protected:
                        confidence = min(confidence, 0.69)
                    candidates.append(RepairCandidate(
                        frame=frame_index, type="outline_gap", action="add", pixels=(point,),
                        confidence=confidence, color=_dominant(colors), protected=protected,
                        details={"direction": direction, "strong_continuation": strong_continuation},
                    ))
                    break

        foreground_components = sorted(_components(occupied, rgba.width, rgba.height), key=len, reverse=True)
        for component in foreground_components[1:]:
            if len(component) > profile.max_orphan_pixels:
                continue
            protected = any(self._protected(point, bbox, profile) for point in component)
            candidates.append(RepairCandidate(
                frame=frame_index, type="orphan_pixel", action="remove", pixels=tuple(sorted(component)),
                confidence=0.69 if protected else 0.97, protected=protected,
                details={"component_size": len(component)},
            ))
        return self._dedupe(candidates)

    @staticmethod
    def _protected(point: Coord, bbox: tuple[int, int, int, int], profile: RepairProfile) -> bool:
        left, top, right, bottom = bbox
        width = max(1, right - left)
        height = max(1, bottom - top)
        nx = (point[0] - left) / width
        ny = (point[1] - top) / height
        return any(x0 <= nx <= x1 and y0 <= ny <= y1 for x0, y0, x1, y1 in profile.protected_regions)

    @staticmethod
    def _dedupe(candidates: list[RepairCandidate]) -> list[RepairCandidate]:
        result: dict[tuple[int, str, tuple[Coord, ...]], RepairCandidate] = {}
        for candidate in candidates:
            key = (candidate.frame, candidate.action, candidate.pixels)
            previous = result.get(key)
            if previous is None or candidate.confidence > previous.confidence:
                result[key] = candidate
        return sorted(result.values(), key=lambda item: (item.frame, -item.confidence, item.type, item.pixels))
