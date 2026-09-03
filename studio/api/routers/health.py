# SPDX-License-Identifier: Apache-2.0
"""GET /api/health, GET /api/providers — ENDPOINTS.md §Health."""

from __future__ import annotations

from fastapi import APIRouter

from studio.api.contracts import ProviderStatusModel
from studio.backend import spritegen_bridge

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/providers", response_model=list[ProviderStatusModel])
def providers() -> list[ProviderStatusModel]:
    return [
        ProviderStatusModel(name=s.name, available=s.available, message=s.message, detail=s.detail)
        for s in spritegen_bridge.provider_status()
    ]
