# SPDX-License-Identifier: MIT
"""Data-driven presets, split by mode (spec §3.2 "Mod-friendly").

Sprite presets describe a unit (directions, states, locks); static presets
describe an asset type (tileability, layer intent, export size, refine
overrides). They live in separate directories and are looked up through
separate functions so a UI cannot offer a tile-set preset to a character run.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from studio.shared.modes import SPRITE, STATIC, resolve_asset_type, resolve_mode


DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "presets"
STATIC_DIR = DATA_DIR / "static"


def _preset_dir(mode: str) -> Path:
    return DATA_DIR if resolve_mode(mode).id == SPRITE else STATIC_DIR


def list_presets(mode: str = SPRITE) -> list[str]:
    directory = _preset_dir(mode)
    if not directory.is_dir():
        return []
    return sorted(path.stem for path in directory.glob("*.json"))


def load_preset(preset_id: str, mode: str = SPRITE) -> dict[str, Any]:
    directory = _preset_dir(mode)
    path = directory / f"{preset_id}.json"
    if not path.is_file():
        raise ValueError(f"unknown preset: {preset_id!r}; available: {', '.join(list_presets(mode))}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("id") != preset_id:
        raise ValueError(f"invalid preset file: {path}")
    if resolve_mode(mode).id == STATIC:
        # Validate the declared asset type at load time so a malformed preset
        # fails where it is read, not later inside a refine engine.
        resolve_asset_type(STATIC, data.get("asset_type"))
    return data


def preset_states(preset: dict[str, Any], selected: list[str] | None = None) -> dict[str, dict[str, Any]]:
    source = preset.get("states") or {}
    names = selected or list(source)
    result: dict[str, dict[str, Any]] = {}
    for name in names:
        if name not in source:
            raise ValueError(f"preset {preset['id']!r} has no state {name!r}")
        result[name] = dict(source[name])
    return result


def list_static_presets() -> list[str]:
    return list_presets(STATIC)


def load_static_preset(preset_id: str) -> dict[str, Any]:
    return load_preset(preset_id, STATIC)
