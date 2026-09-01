# SPDX-License-Identifier: Apache-2.0
"""Analyzer → deterministic/temporal repair orchestration."""

from __future__ import annotations

from collections import Counter
from typing import Any, Sequence

from PIL import Image

from .analyzer import RepairAnalyzer
from .engine import DeterministicRepairEngine
from .models import RepairCandidate, RepairResult
from .profile import RepairProfile
from .temporal import TemporalRepairEngine
from .thin_feature import ThinFeatureAnalyzer


class RepairPipeline:
    def __init__(self) -> None:
        self.analyzer = RepairAnalyzer()
        self.temporal = TemporalRepairEngine()
        self.thin_feature = ThinFeatureAnalyzer()
        self.engine = DeterministicRepairEngine()

    def analyze(
        self,
        frames: list[Image.Image],
        *,
        state: str,
        profile: RepairProfile | None = None,
        residuals: Sequence[dict[str, Any]] = (),
    ) -> list[RepairCandidate]:
        profile = profile or RepairProfile()
        candidates = [candidate for index, frame in enumerate(frames)
                      for candidate in self.analyzer.analyze(frame, frame_index=index, profile=profile)]
        candidates.extend(candidate for index, frame in enumerate(frames)
                          for candidate in self.thin_feature.analyze(frame, frame_index=index, profile=profile))
        for index in range(1, len(frames) - 1):
            candidates.extend(self.temporal.analyze(
                frames[index - 1], frames[index], frames[index + 1],
                frame_index=index, state=state, profile=profile,
            ))
        if residuals:
            candidates.extend(_residual_candidates(frames, residuals, profile))

        deduped: dict[tuple[int, str, tuple[tuple[int, int], ...]], RepairCandidate] = {}
        for candidate in candidates:
            key = (candidate.frame, candidate.action, candidate.pixels)
            previous = deduped.get(key)
            if previous is None or candidate.confidence > previous.confidence:
                deduped[key] = candidate
        return sorted(deduped.values(), key=lambda item: (item.frame, -item.confidence, item.type, item.pixels))

    def repair(
        self,
        frames: list[Image.Image],
        *,
        state: str,
        profile: RepairProfile | None = None,
        candidate_ids: set[str] | None = None,
        residuals: Sequence[dict[str, Any]] = (),
    ) -> RepairResult:
        profile = profile or RepairProfile()
        candidates = self.analyze(frames, state=state, profile=profile, residuals=residuals)
        palette = {color for frame in frames for color in frame.convert("RGBA").get_flattened_data() if color[3] > 0}
        return self.engine.repair(frames, candidates, palette=palette, profile=profile,
                                  candidate_ids=candidate_ids)


def _residual_candidates(
    frames: list[Image.Image],
    residuals: Sequence[dict[str, Any]],
    profile: RepairProfile,
) -> list[RepairCandidate]:
    candidates: list[RepairCandidate] = []
    for item in residuals:
        frame_idx = item.get("frame")
        if not isinstance(frame_idx, int) or not (0 <= frame_idx < len(frames)):
            continue
        pixels = item.get("pixels") or []
        if not pixels and "logical_region" in item:
            region = item["logical_region"]
            rx, ry, rw, rh = region.get("x", 0), region.get("y", 0), region.get("w", 1), region.get("h", 1)
            pixels = [[rx + dx, ry + dy] for dy in range(rh) for dx in range(rw)]
        if not pixels:
            continue
        frame = frames[frame_idx].convert("RGBA")
        bbox = frame.getchannel("A").getbbox() or (0, 0, frame.width, frame.height)
        for px, py in pixels:
            if not (0 <= px < frame.width and 0 <= py < frame.height):
                continue
            if frame.getpixel((px, py))[3] > profile.alpha_threshold:
                continue
            neighbor_colors = []
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    if dx == 0 and dy == 0:
                        continue
                    nx, ny = px + dx, py + dy
                    if 0 <= nx < frame.width and 0 <= ny < frame.height:
                        col = frame.getpixel((nx, ny))
                        if col[3] > profile.alpha_threshold:
                            neighbor_colors.append(col)
            if not neighbor_colors and len(frames) > 1:
                for t_idx in (frame_idx - 1, frame_idx + 1):
                    if 0 <= t_idx < len(frames):
                        col = frames[t_idx].convert("RGBA").getpixel((px, py))
                        if col[3] > profile.alpha_threshold:
                            neighbor_colors.append(col)
            if not neighbor_colors:
                continue
            color = Counter(neighbor_colors).most_common(1)[0][0]
            protected = RepairAnalyzer._protected((px, py), bbox, profile)
            confidence = profile.residual_protected_confidence if protected else profile.residual_normal_confidence
            candidates.append(
                RepairCandidate(
                    frame=frame_idx,
                    type="thin_feature_at_risk",
                    action="add",
                    pixels=((px, py),),
                    confidence=confidence,
                    color=color,
                    engine="deterministic",
                    protected=protected,
                    details={
                        "evidence": item.get("evidence", {}),
                        "source": "refine_residual",
                    },
                )
            )
    return candidates
