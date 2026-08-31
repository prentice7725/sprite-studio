# SPDX-License-Identifier: Apache-2.0
"""Transactional application of safe repair candidates."""

from __future__ import annotations

from collections import Counter

from PIL import Image

from .models import RepairCandidate, RepairChange, RepairResult
from .profile import RepairProfile


class DeterministicRepairEngine:
    def repair(self, frames: list[Image.Image], candidates: list[RepairCandidate], *,
               palette: set[tuple[int, int, int, int]] | None = None,
               profile: RepairProfile | None = None,
               candidate_ids: set[str] | None = None) -> RepairResult:
        profile = profile or RepairProfile()
        repaired = [frame.convert("RGBA").copy() for frame in frames]
        if not repaired:
            return RepairResult((), tuple(candidates), (), ())
        palette = palette or {color for frame in repaired for color in frame.getdata() if color[3] > 0}
        changes: list[RepairChange] = []
        skipped: list[dict] = []
        added_per_frame: Counter[int] = Counter()
        occupied_per_frame = [sum(frame.getchannel("A").histogram()[profile.alpha_threshold + 1:]) for frame in repaired]
        for candidate in sorted(candidates, key=lambda item: (item.frame, -item.confidence, item.id)):
            reason = self._skip_reason(candidate, profile, candidate_ids)
            if reason is None and not (0 <= candidate.frame < len(repaired)):
                reason = "frame-out-of-range"
            if reason is None and candidate.action == "add":
                if candidate.color is None or candidate.color not in palette:
                    reason = "palette-violation"
                projected = added_per_frame[candidate.frame] + len(candidate.pixels)
                ratio_limit = max(1, round(occupied_per_frame[candidate.frame] * profile.max_added_ratio))
                if projected > min(profile.max_added_pixels, ratio_limit):
                    reason = "silhouette-expansion-limit"
            if reason is not None:
                skipped.append({"candidate_id": candidate.id, "reason": reason})
                continue
            frame = repaired[candidate.frame]
            changed: list[tuple[int, int]] = []
            for x, y in candidate.pixels:
                if not (0 <= x < frame.width and 0 <= y < frame.height):
                    continue
                current = frame.getpixel((x, y))
                if candidate.action == "add" and current[3] <= profile.alpha_threshold:
                    frame.putpixel((x, y), candidate.color)
                    changed.append((x, y))
                elif candidate.action == "remove" and current[3] > profile.alpha_threshold:
                    frame.putpixel((x, y), (0, 0, 0, 0))
                    changed.append((x, y))
            if not changed:
                skipped.append({"candidate_id": candidate.id, "reason": "no-op"})
                continue
            if candidate.action == "add":
                added_per_frame[candidate.frame] += len(changed)
            changes.append(RepairChange(candidate.id, candidate.frame, candidate.engine, candidate.type,
                                        candidate.action, tuple(changed), candidate.confidence))
        return RepairResult(tuple(repaired), tuple(candidates), tuple(changes), tuple(skipped))

    @staticmethod
    def _skip_reason(candidate: RepairCandidate, profile: RepairProfile,
                     candidate_ids: set[str] | None) -> str | None:
        if candidate.protected:
            return "protected-region"
        if candidate_ids is not None:
            return None if candidate.id in candidate_ids else "not-selected"
        if candidate.type == "small_hole" and not profile.apply_small_holes:
            return "hole-fill-disabled"
        if candidate.engine == "temporal" and not profile.apply_temporal:
            return "temporal-disabled"
        threshold = profile.safe_thresholds.get(candidate.type, 1.01)
        if candidate.confidence < threshold:
            return "below-safe-threshold"
        return None
