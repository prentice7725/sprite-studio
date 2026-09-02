# SPDX-License-Identifier: Apache-2.0
"""Prompt QA before a provider call."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class PromptIssue:
    severity: Literal["warning", "error"]
    code: str
    message: str


class PromptValidator:
    """Validate safety clauses without trying to judge visual quality.

    `target_kind` (SPRITE_STUDIO_PROMPT_PIPELINE_REGRESSION_FIX_DIRECTIVE §2)
    splits the single-subject rule from the animation-row rule: a "single"
    prompt must keep "single character only"; an "animation_row" prompt must
    NEVER carry that clause (it contradicts "same character repeated once per
    slot") and must instead carry its own exact-frame-count / slot contract.
    """

    def validate(self, prompt: str, *, target_kind: str = "single") -> list[PromptIssue]:
        lowered = prompt.lower()
        required = [
            ("full body", "FULL_BODY", "full body clause is missing"),
            ("no drop shadow", "NO_SHADOW", "no-shadow clause is missing"),
            ("no blur", "NO_BLUR", "no-blur clause is missing"),
            ("no cropped", "NOT_CROPPED", "not-cropped clause is missing"),
        ]
        if target_kind == "single":
            required.append(("single character", "SINGLE_SUBJECT", "single character clause is missing"))
        issues = [PromptIssue("error", code, message) for needle, code, message in required if needle not in lowered]
        if target_kind == "animation_row":
            if "single character only" in lowered:
                issues.append(PromptIssue(
                    "error", "SINGLE_SUBJECT_IN_ROW",
                    "row prompt still carries 'single character only', which contradicts the "
                    "same-character-per-slot row contract",
                ))
            if "exactly" not in lowered or "slot" not in lowered:
                issues.append(PromptIssue(
                    "error", "ROW_CONTRACT_MISSING",
                    "row prompt is missing the exact-frame-count / slot contract",
                ))
        if "direct_pixel" not in lowered and "refine_first" not in lowered and "pixel art" not in lowered and "flat-color" not in lowered:
            issues.append(PromptIssue("error", "PROFILE_MISSING", "generation profile style clause is missing"))
        if "background" not in lowered and "#00ff00" not in lowered and "#ff00ff" not in lowered:
            issues.append(PromptIssue("warning", "BACKGROUND_MISSING", "solid background clause is missing"))
        if "attack" in lowered and not any(needle in lowered for needle in ("same physical weapon hand", "never swap hands", "consistent facing")):
            issues.append(PromptIssue("warning", "HANDEDNESS_CONSTRAINT_MISSING", "attack prompt does not explicitly lock weapon hand continuity"))
        return issues

    def require_valid(self, prompt: str, *, target_kind: str = "single") -> None:
        issues = self.validate(prompt, target_kind=target_kind)
        errors = [issue.message for issue in issues if issue.severity == "error"]
        if errors:
            raise ValueError("prompt validation failed: " + "; ".join(errors))
