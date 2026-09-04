from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

import studio.api.routers.generate as generate_router
from studio.api.routers.static_mode import _action
from sprite_studio.gen.base import GenTimeoutError


def test_generate_maps_provider_timeout_to_gateway_timeout(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(generate_router, "load_run_and_request", lambda run_id: (tmp_path, {"states": {"idle": {}}}))
    monkeypatch.setattr(generate_router, "require_state", lambda request, state: None)
    monkeypatch.setattr(
        generate_router.spritegen_bridge,
        "generate_state",
        lambda run_dir, state: (_ for _ in ()).throw(GenTimeoutError("provider stalled")),
    )

    with pytest.raises(HTTPException) as caught:
        generate_router.generate("run", "idle")

    assert caught.value.status_code == 504
    assert "provider stalled" in str(caught.value.detail)


def test_static_action_maps_provider_timeout_to_gateway_timeout() -> None:
    with pytest.raises(HTTPException) as caught:
        _action(lambda: (_ for _ in ()).throw(GenTimeoutError("provider stalled")))

    assert caught.value.status_code == 504
    assert "provider stalled" in str(caught.value.detail)
