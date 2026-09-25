from __future__ import annotations

from fastapi.testclient import TestClient

from studio.api.main import app
from studio.api.contracts import QuickMakeSpriteRequest


client = TestClient(app)


def test_quick_make_contract_separates_pixel_master_and_generation_strategies() -> None:
    request = QuickMakeSpriteRequest(pixelize=True)
    assert request.generation_strategy == "AUTO"
    assert request.strategy == "preserve"


def test_quick_c2_strategy_is_rejected_by_the_product_api() -> None:
    response = client.post("/api/quick/sessions/legacy/pixelize", json={
        "strategy": "reference_pixel_master_128",
        "size": 128,
    })
    assert response.status_code == 422
    assert any(error["loc"][-1] == "strategy" for error in response.json()["detail"])
