from __future__ import annotations

from fastapi.testclient import TestClient

from studio.api.main import app


client = TestClient(app)


def test_static_c2_strategy_is_rejected_by_the_product_api() -> None:
    response = client.post("/api/static/no_project/pixelize", json={
        "strategy": "reference_pixel_master_128",
        "size": 128,
    })
    assert response.status_code == 422
    assert any(error["loc"][-1] == "strategy" for error in response.json()["detail"])
