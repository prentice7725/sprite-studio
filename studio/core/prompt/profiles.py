# SPDX-License-Identifier: MIT
"""Data loader for generation and negative prompt profiles."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


PROMPT_DATA = Path(__file__).resolve().parents[2] / "data" / "prompts"


def load_json(relative: str) -> dict[str, Any]:
    path = PROMPT_DATA / relative
    if not path.is_file():
        raise ValueError(f"prompt data not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"prompt data must be an object: {path}")
    return data


def load_generation_profile(profile: str) -> dict[str, Any]:
    profile = profile.lower().strip()
    if profile not in {"direct_pixel", "refine_first"}:
        raise ValueError("generation_profile must be direct_pixel or refine_first")
    return load_json(f"profiles/{profile}.json")


def load_negative_profile(profile: str = "default") -> dict[str, Any]:
    return load_json(f"negatives/{profile}.json")
