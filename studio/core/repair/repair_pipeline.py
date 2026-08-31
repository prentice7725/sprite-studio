# SPDX-License-Identifier: MIT
"""Analyzer → deterministic/temporal repair orchestration."""

from __future__ import annotations

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

    def analyze(self, frames: list[Image.Image], *, state: str,
                profile: RepairProfile | None = None) -> list[RepairCandidate]:
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
        deduped: dict[tuple[int, str, tuple[tuple[int, int], ...]], RepairCandidate] = {}
        for candidate in candidates:
            key = (candidate.frame, candidate.action, candidate.pixels)
            previous = deduped.get(key)
            if previous is None or candidate.confidence > previous.confidence:
                deduped[key] = candidate
        return sorted(deduped.values(), key=lambda item: (item.frame, -item.confidence, item.type, item.pixels))

    def repair(self, frames: list[Image.Image], *, state: str,
               profile: RepairProfile | None = None,
               candidate_ids: set[str] | None = None) -> RepairResult:
        profile = profile or RepairProfile()
        candidates = self.analyze(frames, state=state, profile=profile)
        palette = {color for frame in frames for color in frame.convert("RGBA").get_flattened_data() if color[3] > 0}
        return self.engine.repair(frames, candidates, palette=palette, profile=profile,
                                  candidate_ids=candidate_ids)
