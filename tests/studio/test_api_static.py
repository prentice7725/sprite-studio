# SPDX-License-Identifier: Apache-2.0
"""Static Mode FastAPI contract tests."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from studio.api.main import app
from studio.backend import static_service

client = TestClient(app)


def test_static_project_create_list_prompt_and_status(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SPRITE_STUDIO_STATIC_ROOT", str(tmp_path / "static-projects"))

    created = client.post("/api/static", json={
        "project_id": "forest_demo",
        "provider": "grok",
        "asset_type": "PIXEL_SCENE",
        "description": "A forest clearing with flat color regions and crisp block edges.",
    })
    assert created.status_code == 201
    assert created.json()["project_id"] == "forest_demo"

    listed = client.get("/api/static")
    assert listed.status_code == 200
    assert [item["project_id"] for item in listed.json()] == ["forest_demo"]

    prompt = client.get("/api/static/forest_demo/prompt")
    assert prompt.status_code == 200
    assert "forest clearing" in prompt.json()["prompt"]
    assert client.get("/api/static/forest_demo/status").json() == {"assets": {}}


def test_static_refine_and_export_return_static_asset_urls(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SPRITE_STUDIO_STATIC_ROOT", str(tmp_path / "static-projects"))
    created = client.post("/api/static", json={
        "project_id": "tile_demo",
        "provider": "grok",
        "asset_type": "TILE_SET",
        "tileable": True,
        "description": "A seamless tile with flat color regions and crisp block edges.",
    })
    assert created.status_code == 201
    info = static_service.load_project("tile_demo")
    refined = info.path / "refined" / "scene.png"
    refined.parent.mkdir(parents=True, exist_ok=True)
    refined.write_bytes(b"refined")
    exported = info.path / "export" / "scene.png"
    monkeypatch.setattr(static_service, "refine_asset", lambda *_args, **_kwargs: {"asset": "scene", "grid": {}})
    monkeypatch.setattr(static_service, "export_asset", lambda *_args, **_kwargs: exported)
    exported.write_bytes(b"exported")

    refine = client.post("/api/static/tile_demo/refine", json={"asset": "scene"})
    assert refine.status_code == 200
    assert refine.json()["output_asset"] == "/api/static/tile_demo/assets/refined/scene.png"

    export = client.post("/api/static/tile_demo/export", params={"asset": "scene"})
    assert export.status_code == 200
    assert export.json()["export_asset"] == "/api/static/tile_demo/assets/export/scene.png"
    assert client.get(export.json()["export_asset"]).status_code == 200


def test_static_asset_route_rejects_path_escape(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SPRITE_STUDIO_STATIC_ROOT", str(tmp_path / "static-projects"))
    client.post("/api/static", json={"project_id": "safe_demo", "provider": "grok", "description": "scene"})

    response = client.get("/api/static/safe_demo/assets/../static/project.json")

    assert response.status_code in {400, 404}
