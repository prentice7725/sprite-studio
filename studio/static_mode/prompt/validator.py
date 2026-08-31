# SPDX-License-Identifier: MIT
"""Static Mode prompt QA (spec §10.2).

The Sprite validator cannot be reused here, and the reason is worth stating
because it is the mode split in miniature: it requires "full body", "single
character" and "not cropped" clauses. A ground-texture tile has no body, no
character, and *must* be cropped at every edge — running those checks against a
scene prompt produces four errors that are all correct-by-sprite-rules and all
wrong for the asset being made. A shared validator would therefore either fail
every static prompt or be watered down until it stopped protecting sprites.

What Static actually needs guarded is different:

* refiner-friendliness — flat regions and hard edges, since the static refine
  stage depends on recoverable block structure;
* asset-shape constraints — a tile must claim edge continuity, a prop must
  claim isolation;
* the absence of lens/photographic effects that destroy a pixel lattice.
"""

from __future__ import annotations

from typing import Iterable

from studio.core.prompt.validator import PromptIssue


_REFINER_CLAUSES = ("flat readable color", "flat color", "large flat", "flat regions", "crisp block edges", "hard edges")
_SOFTNESS_BANS = ("no gradient", "no soft focus", "no soft edges", "no gradient falloff", "no gradient banding")


class StaticPromptValidator:
    """Validate a scene/object prompt for refine-friendliness and asset shape."""

    def validate(self, prompt: str, *, asset_type: str = "PIXEL_SCENE", tileable: bool = False) -> list[PromptIssue]:
        lowered = prompt.lower()
        issues: list[PromptIssue] = []

        if not _any_of(lowered, _REFINER_CLAUSES):
            issues.append(
                PromptIssue("error", "FLAT_REGIONS_MISSING", "prompt does not ask for flat colour regions the static refiner can snap")
            )
        if not _any_of(lowered, _SOFTNESS_BANS):
            issues.append(
                PromptIssue("error", "SOFTNESS_NOT_BANNED", "prompt does not exclude gradients/soft focus, which destroy the pixel lattice")
            )
        if "no text" not in lowered:
            issues.append(PromptIssue("warning", "TEXT_NOT_BANNED", "prompt does not exclude text or watermarks"))
        if "background" not in lowered and "transparent" not in lowered:
            issues.append(PromptIssue("warning", "BACKGROUND_MISSING", "background policy clause is missing"))

        normalized = str(asset_type).upper()
        if normalized == "TILE_SET" or tileable:
            if not _any_of(lowered, ("tileable", "seamless", "continues across every edge", "continues past every border")):
                issues.append(
                    PromptIssue("error", "TILEABILITY_MISSING", "a tileable asset must state edge continuity explicitly")
                )
            if "vignette" in lowered and "no vignette" not in lowered:
                issues.append(PromptIssue("warning", "VIGNETTE_RISK", "vignetting breaks tile repetition"))
        if normalized == "PROP_OBJECT" and not _any_of(lowered, ("single isolated object", "one object only", "single object")):
            issues.append(
                PromptIssue("error", "ISOLATION_MISSING", "a prop must state that it is a single isolated object")
            )
        if normalized in {"PIXEL_SCENE", "FLAT_SCENE"} and not _any_of(lowered, ("background", "midground", "foreground")):
            issues.append(
                PromptIssue("warning", "LAYERING_MISSING", "scene prompt does not describe depth bands, which layer split relies on")
            )
        return issues

    def require_valid(self, prompt: str, **kwargs: object) -> None:
        issues = self.validate(prompt, **kwargs)  # type: ignore[arg-type]
        errors = [issue.message for issue in issues if issue.severity == "error"]
        if errors:
            raise ValueError("static prompt validation failed: " + "; ".join(errors))


def _any_of(text: str, needles: Iterable[str]) -> bool:
    return any(needle in text for needle in needles)
