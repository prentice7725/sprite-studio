# SPDX-License-Identifier: MIT
"""Deep Prompt Assembly Module: blocks in, reproducible prompt out."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .background_policy import resolve_background
from .profiles import load_generation_profile, load_negative_profile
from .validator import PromptIssue, PromptValidator


@dataclass(frozen=True)
class PromptResult:
    character_id: str
    direction: str
    state: str
    generation_profile: str
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
        background_policy: str = "auto",
        negative_profile: str = "default",
        identity: str = "",
        base_image: Path | None = None,
        action_text: str | None = None,
    ) -> PromptResult:
        profile = load_generation_profile(generation_profile)
        negative = load_negative_profile(negative_profile)
        background = resolve_background(background_policy, base_image)
        if background["policy"] == "transparent":
            background_block = "transparent background with clean alpha, no matte"
        else:
            background_block = (
                f"full frame edge-to-edge solid bright {background['name']} background "
                f"({background['hex']})"
            )
        action = self._action(direction, state, action_text=action_text)
        blocks = {
            "identity": identity.strip() or character_id,
            "direction_action": action,
            "style_profile": str(profile["style"]),
            "refiner_safe_suffix": str(profile["safe_suffix"]).replace("{{BACKGROUND}}", background_block),
            "negative": str(negative["text"]),
        }
        final_prompt = "\n\n".join(blocks.values())
        issues = tuple(self.validator.validate(final_prompt))
        return PromptResult(character_id, direction, state, generation_profile, background, blocks, final_prompt, issues)

    @staticmethod
    def _action(direction: str, state: str, *, action_text: str | None = None) -> str:
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
        return f"{facing},\n{action},\n4-frame readable motion when this is an animation row"
