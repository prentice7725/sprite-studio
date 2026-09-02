# SPDX-License-Identifier: Apache-2.0
"""Deep Prompt Assembly Module: blocks in, reproducible prompt out."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .background_policy import resolve_background
from .profiles import load_generation_profile, load_negative_profile
from .validator import PromptIssue, PromptValidator


# SPRITE_STUDIO_PROMPT_PIPELINE_REGRESSION_FIX_DIRECTIVE §2: the prompt target
# kind decides which subject clause and which negative profile apply. A row
# ("animation_row", frames > 1) must never carry "single character only" — the
# whole point of a row is the SAME character repeated once per slot — and a
# true single-image target must keep it. frames <= 1 reads as "single".
_SUBJECT_CLAUSES = {
    "single": "single character only",
    "animation_row": (
        "the same character repeated exactly once in every requested animation "
        "slot, no unrelated secondary characters"
    ),
}


def target_kind_for(frames: int) -> str:
    return "single" if frames <= 1 else "animation_row"


@dataclass(frozen=True)
class PromptResult:
    character_id: str
    direction: str
    state: str
    generation_profile: str
    target_kind: str
    frame_count: int
    background: dict[str, Any]
    blocks: dict[str, str]
    final_prompt: str
    issues: tuple[PromptIssue, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "sprite-studio-prompt-manifest",
            "character_id": self.character_id,
            "direction": self.direction,
            "state": self.state,
            "generation_profile": self.generation_profile,
            "target_kind": self.target_kind,
            "frame_count": self.frame_count,
            "background": self.background,
            "blocks": self.blocks,
            "final_prompt": self.final_prompt,
            "issues": [issue.__dict__ for issue in self.issues],
        }


class PromptAssembler:
    def __init__(self, *, validator: PromptValidator | None = None) -> None:
        self.validator = validator or PromptValidator()

    def assemble(
        self,
        character_id: str,
        direction: str,
        state: str,
        generation_profile: str,
        *,
        frames: int,
        background_policy: str = "auto",
        negative_profile: str = "auto",
        identity: str = "",
        base_image: Path | None = None,
        action_text: str | None = None,
    ) -> PromptResult:
        target_kind = target_kind_for(frames)
        profile = load_generation_profile(generation_profile)
        resolved_negative_profile = negative_profile
        if negative_profile == "auto":
            resolved_negative_profile = "default" if target_kind == "single" else "animation_row"
        negative = load_negative_profile(resolved_negative_profile)
        background = resolve_background(background_policy, base_image)
        if background["policy"] == "transparent":
            background_block = "transparent background with clean alpha, no matte"
        else:
            background_block = (
                f"full frame edge-to-edge solid bright {background['name']} background "
                f"({background['hex']})"
            )
        action = self._action(direction, state, frames, target_kind, action_text=action_text)
        safe_suffix = str(profile["safe_suffix"])
        safe_suffix = safe_suffix.replace("{{SUBJECT}}", _SUBJECT_CLAUSES[target_kind])
        safe_suffix = safe_suffix.replace("{{BACKGROUND}}", background_block)
        blocks = {
            "identity": identity.strip() or character_id,
            "direction_action": action,
            "style_profile": str(profile["style"]),
            "refiner_safe_suffix": safe_suffix,
            "negative": str(negative["text"]),
        }
        final_prompt = "\n\n".join(blocks.values())
        issues = tuple(self.validator.validate(final_prompt, target_kind=target_kind))
        return PromptResult(
            character_id, direction, state, generation_profile, target_kind, frames,
            background, blocks, final_prompt, issues,
        )

    @staticmethod
    def _action(direction: str, state: str, frames: int, target_kind: str, *, action_text: str | None = None) -> str:
        facing = {
            "down": "front-facing game sprite view, clear front silhouette",
            "side": "side-facing game sprite view, clear side silhouette",
            "up": "back-facing game sprite view, clear rear silhouette",
            "left": "side-facing game sprite view facing camera-left, clear side silhouette",
            "right": "side-facing game sprite view facing camera-right, clear side silhouette",
        }.get(direction, f"{direction}-facing game sprite view, clear silhouette")
        default_action = {
            "idle": "neutral balanced idle pose, subtle ready stance",
            "attack": "clear practical infantry sword attack, readable attack motion: ready, windup, strike, recovery",
            "move": "readable locomotion cycle with clear contact and passing poses",
            "hit": "readable hit reaction while preserving the same character identity",
            "down": "readable defeated pose with the same character identity",
        }.get(state, f"readable {state} action")
        action = action_text or default_action
        continuity = "same physical weapon hand in every frame, never swap hands, never mirror handedness, keep the weapon attached to the same arm and maintain one consistent facing"
        if state == "attack":
            action = f"{action},\n{continuity}"
        # §4: frame count always comes from the caller's SSOT (request["states"][state]["frames"]),
        # never a hardcoded literal — a 4-frame request reads "Exactly 4", a 6-frame request "Exactly 6".
        if target_kind == "animation_row":
            motion_line = (
                f"Exactly {frames} full-body animation poses of the same character in this row, "
                f"one complete pose per slot, readable motion progression across the sequence"
            )
        else:
            motion_line = "single full-body pose, no animation row"
        return f"{facing},\n{action},\n{motion_line}"
