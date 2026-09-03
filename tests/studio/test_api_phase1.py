# SPDX-License-Identifier: Apache-2.0
"""Phase 1 FastAPI shell — health/providers, run list/get/status, asset
serving (ENDPOINTS.md). Routers must stay thin: these tests pin that the
response shape matches `studio.api.contracts`, not that the underlying
backend logic is correct (that's already covered where each backend function
lives)."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from studio.api.main import app
from studio.backend import run_manager
from studio.backend.run_manager import RUNS_ROOT_ENV
from studio.backend.schemas import StudioRunConfig

client = TestClient(app)


def _base(path: Path) -> None:
    image = Image.new("RGB", (64, 64), (255, 0, 255))
    ImageDraw.Draw(image).rectangle((22, 16, 42, 55), fill=(80, 80, 80))
    image.save(path)


def _seed_run(tmp_path: Path, monkeypatch) -> str:
    runs_root = tmp_path / "runs"
    monkeypatch.setenv(RUNS_ROOT_ENV, str(runs_root))
    base = tmp_path / "base.png"
    _base(base)
    config = StudioRunConfig(
        run_id="api_test_run",
        character_id="sword",
        provider="grok",
        base_image=base,
        directions=("side",),
        mirrors={},
        states={"idle": {"frames": 4, "fps": 4, "loop": True, "action": "idle"}},
        preset="sword",
    )
    run_manager.create_run(config, root=runs_root)
    return "api_test_run"


def test_health() -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_providers_shape() -> None:
    response = client.get("/api/providers")
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    for entry in body:
        assert {"name", "available", "message"} <= set(entry)


def test_list_runs_empty_when_no_runs_root(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv(RUNS_ROOT_ENV, str(tmp_path / "runs"))
    response = client.get("/api/runs")
    assert response.status_code == 200
    assert response.json() == []


def test_get_run_not_found_is_404(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv(RUNS_ROOT_ENV, str(tmp_path / "runs"))
    response = client.get("/api/runs/does_not_exist")
    assert response.status_code == 404
    assert "detail" in response.json()


def test_list_get_status_round_trip(tmp_path: Path, monkeypatch) -> None:
    run_id = _seed_run(tmp_path, monkeypatch)

    listed = client.get("/api/runs")
    assert listed.status_code == 200
    assert [r["run_id"] for r in listed.json()] == [run_id]
    summary = listed.json()[0]
    assert summary["directions"] == ["side"]
    assert summary["states"] == ["side_idle"]

    detail = client.get(f"/api/runs/{run_id}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["run_id"] == run_id
    assert body["generation_profile"] == "refine_first"
    assert body["cell_size"] == 256

    status = client.get(f"/api/runs/{run_id}/status")
    assert status.status_code == 200
    assert status.json()["states"] == {"side_idle": "not-generated"}


def test_asset_serving_streams_a_real_file(tmp_path: Path, monkeypatch) -> None:
    run_id = _seed_run(tmp_path, monkeypatch)

    response = client.get(f"/api/runs/{run_id}/assets/sprite-request.json")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert b'"kind"' in response.content


def test_asset_serving_rejects_path_traversal(tmp_path: Path, monkeypatch) -> None:
    run_id = _seed_run(tmp_path, monkeypatch)

    response = client.get(f"/api/runs/{run_id}/assets/../../../../etc/passwd")
    # Starlette normalizes `..` in the path template match itself for some
    # forms; whichever way it lands, this must never be a 200 with file
    # content from outside the run directory.
    assert response.status_code in (400, 404)


def test_asset_serving_missing_file_is_404(tmp_path: Path, monkeypatch) -> None:
    run_id = _seed_run(tmp_path, monkeypatch)

    response = client.get(f"/api/runs/{run_id}/assets/does/not/exist.png")
    assert response.status_code == 404
