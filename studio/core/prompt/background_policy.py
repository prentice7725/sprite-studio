# SPDX-License-Identifier: MIT
"""Deterministic prompt background policy."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sprite_studio.gen.prepare import choose_chroma_key


POLICIES = ("auto", "green", "magenta", "red", "blue", "transparent")
_FIXED = {
    "green": {"name": "green", "hex": "#00FF00", "rgb": [0, 255, 0]},
    "magenta": {"name": "magenta", "hex": "#FF00FF", "rgb": [255, 0, 255]},
    "red": {"name": "red", "hex": "#FF0000", "rgb": [255, 0, 0]},
    "blue": {"name": "blue", "hex": "#004DFF", "rgb": [0, 77, 255]},
}


def resolve_background(policy: str, base_image: Path | None = None) -> dict[str, Any]:
    policy = policy.lower().strip()
    if policy not in POLICIES:
        raise ValueError(f"unknown background policy {policy!r}; expected one of {', '.join(POLICIES)}")
    if policy == "transparent":
        return {"policy": policy, "name": "transparent", "hex": None, "rgb": None}
    if policy == "auto":
        selected = choose_chroma_key(base_image, "auto")
        return {"policy": policy, **selected}
    return {"policy": policy, **_FIXED[policy]}
