# SPDX-License-Identifier: Apache-2.0
"""Data-driven Sprite Mode preset endpoints."""

from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter, HTTPException

from studio.backend import preset_service

router = APIRouter(prefix="/presets", tags=["presets"])


def _action(action: Callable[[], Any]) -> Any:
    try:
        return action()
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("", response_model=list[str])
def list_sprite_presets() -> list[str]:
    return _action(preset_service.list_presets)


@router.get("/{preset_id}")
def get_sprite_preset(preset_id: str) -> dict[str, Any]:
    return _action(lambda: preset_service.load_preset(preset_id))
