# SPDX-License-Identifier: Apache-2.0
"""POST /api/uploads and POST/DELETE /api/runs — ENDPOINTS.md §Uploads and
§"Sprite Mode — Project / Runs" (the create/delete slice Phase 1 deferred)."""

from __future__ import annotations

import io
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from studio.api.main import app
from studio.api.uploads import UPLOADS_ROOT_ENV
from studio.backend.run_manager import RUNS_ROOT_ENV

client = TestClient(app)


def _png_bytes() -> bytes:
    image = Image.new("RGB", (64, 64), (10, 10, 10))
    ImageDraw.Draw(image).rectangle((22, 16, 42, 55), fill=(80, 80, 80))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _isolate(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv(RUNS_ROOT_ENV, str(tmp_path / "runs"))
    monkeypatch.setenv(UPLOADS_ROOT_ENV, str(tmp_path / "uploads"))


# --- Uploads ---------------------------------------------------------------

def test_upload_valid_image(tmp_path: Path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    response = client.post("/api/uploads", files={"file": ("base.png", _png_bytes(), "image/png")})
    assert response.status_code == 201
    body = response.json()
    assert body["filename"] == "base.png"
    assert body["upload_id"]
    saved = tmp_path / "uploads" / body["upload_id"] / "base.png"
    assert saved.is_file()


def test_upload_rejects_non_image_bytes(tmp_path: Path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    response = client.post("/api/uploads", files={"file": ("not-an-image.png", b"this is not a png", "image/png")})
    assert response.status_code == 400


def test_upload_rejects_empty_file(tmp_path: Path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    response = client.post("/api/uploads", files={"file": ("empty.png", b"", "image/png")})
    assert response.status_code == 400


def test_upload_strips_path_components_from_filename(tmp_path: Path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    response = client.post("/api/uploads", files={"file": ("../../evil.png", _png_bytes(), "image/png")})
    assert response.status_code == 201
    assert response.json()["filename"] == "evil.png"


# --- Run creation ------------------------------------------------------------

def _minimal_run_body(run_id: str = "api_created_run", **overrides) -> dict:
    body = {
        "run_id": run_id,
        "character_id": "sword",
        "provider": "grok",
        "preset": "sword",
        "directions": ["side"],
        "states": {"idle": {"frames": 4, "fps": 4, "loop": True, "action": "idle"}},
    }
    body.update(overrides)
    return body


def test_create_run_without_base_image(tmp_path: Path, monkeypatch) -> None:
    """§ base image is optional for "Generate New" — the fix from the earlier
    identity_ref/base_source SystemExit incident must hold through the API
    too, not just the Gradio path."""
    _isolate(tmp_path, monkeypatch)
    response = client.post("/api/runs", json=_minimal_run_body())
    assert response.status_code == 201
    body = response.json()
    assert body["run_id"] == "api_created_run"
    assert body["states"] == ["side_idle"]

    listed = client.get("/api/runs")
    assert [r["run_id"] for r in listed.json()] == ["api_created_run"]


def test_create_run_with_uploaded_base_image(tmp_path: Path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    upload = client.post("/api/uploads", files={"file": ("base.png", _png_bytes(), "image/png")})
    upload_id = upload.json()["upload_id"]

    response = client.post("/api/runs", json=_minimal_run_body(base_image_upload_id=upload_id))
    assert response.status_code == 201
    run_id = response.json()["run_id"]

    # The uploaded image actually became the run's base-source file.
    assets = client.get(f"/api/runs/{run_id}/assets/base-source.png")
    assert assets.status_code == 200
    assert assets.content == _png_bytes()


def test_create_run_with_unknown_upload_id_is_404(tmp_path: Path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    response = client.post("/api/runs", json=_minimal_run_body(base_image_upload_id="does-not-exist"))
    assert response.status_code == 404


def test_create_run_duplicate_id_is_409(tmp_path: Path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    assert client.post("/api/runs", json=_minimal_run_body()).status_code == 201
    again = client.post("/api/runs", json=_minimal_run_body())
    assert again.status_code == 409


def test_create_run_no_directions_is_400(tmp_path: Path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    response = client.post("/api/runs", json=_minimal_run_body(directions=[]))
    assert response.status_code == 400


def test_create_run_missing_required_field_is_422(tmp_path: Path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    body = _minimal_run_body()
    del body["provider"]
    response = client.post("/api/runs", json=body)
    assert response.status_code == 422


# --- Run deletion ------------------------------------------------------------

def test_delete_run(tmp_path: Path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    created = client.post("/api/runs", json=_minimal_run_body())
    run_id = created.json()["run_id"]
    assert client.get(f"/api/runs/{run_id}").status_code == 200

    deleted = client.delete(f"/api/runs/{run_id}")
    assert deleted.status_code == 204
    assert deleted.content == b""

    assert client.get(f"/api/runs/{run_id}").status_code == 404


def test_delete_unknown_run_is_404(tmp_path: Path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    assert client.delete("/api/runs/does_not_exist").status_code == 404
