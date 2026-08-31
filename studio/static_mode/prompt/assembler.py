# SPDX-License-Identifier: MIT
"""Static Mode prompt assembly (spec §10.2).

    Scene / Object Description
    + Style Profile
    + Layout / Tileability / Layer Intent
    + Cleanup-friendly Suffix
    + Negative Block

Split from the Sprite prompt for the reason the whole mode split exists: the
two are optimising different things. A sprite prompt spends its budget on
character identity, action legibility and frame consistency. A scene prompt
spends it on composition, repeatability and figure-ground separation — and it
must *not* carry the sprite negatives, half of which ("no background scenery")
would forbid the asset being requested.

Profile loading is Shared Core's (``studio.core.prompt.profiles``); only the
composition is mode-specific.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from studio.core.prompt.background_policy import resolve_background
from studio.core.prompt.profiles import load_json
from studio.core.prompt.validator import PromptIssue
from studio.shared.modes import STATIC, resolve_asset_type

from .validator import StaticPromptValidator


STYLE_PROFILES = ("pixel_scene", "tile_set", "prop_object", "flat_scene")

# Asset type declares what the thing *is*; style profile declares how it should
# look. They line up one-to-one by default, and a project may still pair, say, a
# PROP_OBJECT with the flat_scene style deliberately.
DEFAULT_PROFILE_FOR_TYPE = {
    "PIXEL_SCENE": "pixel_scene",
    "TILE_SET": "tile_set",
    "PROP_OBJECT": "prop_object",
    "FLAT_SCENE": "flat_scene",
}


@dataclass(frozen=True)
class StaticPromptResult:
    project_id: str
    asset_type: str
    style_profile: str
    background: dict[str, Any]
    blocks: dict[str, str]
    final_prompt: str
    issues: tuple[PromptIssue, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "asset-studio-static-prompt-manifest",
            "project_id": self.project_id,
            "asset_type": self.asset_type,
            "style_profile": self.style_profile,
            "background": self.background,
            "blocks": self.blocks,
            "final_prompt": self.final_prompt,
            "issues": [issue.__dict__ for issue in self.issues],
        }


def load_style_profile(profile: str) -> dict[str, Any]:
    key = str(profile).lower().strip()
    if key not in STYLE_PROFILES:
        raise ValueError(f"style_profile must be one of {STYLE_PROFILES} (got {profile!r})")
    return load_json(f"profiles/static/{key}.json")


class StaticPromptAssembler:
    """Blocks in, reproducible scene/object prompt out."""

    def __init__(self, *, validator: StaticPromptValidator | None = None) -> None:
        self.validator = validator or StaticPromptValidator()

    def assemble(
        self,
        project_id: str,
        description: str,
        *,
        asset_type: str = "PIXEL_SCENE",
        style_profile: str | None = None,
        tileable: bool = False,
        layer_intent: str = "none",
        background_policy: str = "auto",
        negative_profile: str = "static",
        base_image: Path | None = None,
        export_size: tuple[int, int] | None = None,
    ) -> StaticPromptResult:
        resolved_type = resolve_asset_type(STATIC, asset_type)
        profile_id = style_profile or DEFAULT_PROFILE_FOR_TYPE[resolved_type]
        profile = load_style_profile(profile_id)
        negative = load_json(f"negatives/{negative_profile}.json")
        background = resolve_background(background_policy, base_image)
        if background["policy"] == "transparent":
            background_block = "transparent background with clean alpha, no matte"
        else:
            background_block = (
                f"full frame edge-to-edge solid bright {background['name']} background ({background['hex']})"
            )
        blocks = {
            "description": description.strip() or f"{resolved_type.lower().replace('_', ' ')} asset",
            "style_profile": str(profile["style"]),
            "layout": self._layout(resolved_type, tileable=tileable, layer_intent=layer_intent, export_size=export_size),
            "cleanup_suffix": str(profile["cleanup_suffix"]).replace("{{BACKGROUND}}", background_block),
            "negative": str(negative["text"]),
        }
        final_prompt = "\n\n".join(blocks.values())
        return StaticPromptResult(
            project_id=project_id,
            asset_type=resolved_type,
            style_profile=profile_id,
            background=background,
            blocks=blocks,
            final_prompt=final_prompt,
            issues=tuple(self.validator.validate(final_prompt, asset_type=resolved_type, tileable=tileable)),
        )

    @staticmethod
    def _layout(
        asset_type: str,
        *,
        tileable: bool,
        layer_intent: str,
        export_size: tuple[int, int] | None,
    ) -> str:
        parts: list[str] = []
        if asset_type == "TILE_SET" or tileable:
            # Stated twice on purpose — once as intent, once as the concrete
            # constraint. Image models drop a lone abstract adjective like
            # "seamless" far more often than they drop a described geometry.
            parts.append(
                "seamless tileable square texture, the pattern continues across every edge so the left edge "
                "matches the right edge and the top edge matches the bottom edge when repeated"
            )
        if asset_type == "PROP_OBJECT":
            parts.append("single isolated object, centered, clean separation from the background on all sides")
        if asset_type in {"PIXEL_SCENE", "FLAT_SCENE"}:
            parts.append("clear scene composition with distinct background, midground and foreground bands")
        if layer_intent and layer_intent != "none":
            parts.append(f"composed so the {layer_intent} can be separated as its own layer")
        if export_size:
            parts.append(f"square framing intended for a {export_size[0]}x{export_size[1]} asset")
        return ",\n".join(parts) if parts else "straightforward centered composition"


def assemble_static_prompt(*args: Any, **kwargs: Any) -> StaticPromptResult:
    return StaticPromptAssembler().assemble(*args, **kwargs)
