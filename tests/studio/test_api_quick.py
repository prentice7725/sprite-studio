# SPDX-License-Identifier: Apache-2.0
"""Quick Generate source-first API contract tests."""

from __future__ import annotations

import io
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from studio.api.main import app
from studio.api.uploads import UPLOADS_ROOT_ENV
from studio.backend import quick_service
from studio.backend.run_manager import RUNS_ROOT_ENV


client = TestClient(app)


def _png_bytes() -> bytes:
    image = Image.new("RGBA", (96, 64), (0, 0, 0, 0))
    ImageDraw.Draw(image).rectangle((30, 10, 66, 58), fill=(50, 120, 220, 255))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _isolate(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv(RUNS_ROOT_ENV, str(tmp_path / "runs"))
    monkeypatch.setenv(UPLOADS_ROOT_ENV, str(tmp_path / "uploads"))
    monkeypatch.setenv(quick_service.QUICK_ROOT_ENV, str(tmp_path / "quick"))


def test_quick_upload_pixelize_and_explicit_source_selection(tmp_path: Path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    upload = client.post("/api/uploads", files={"file": ("character.png", _png_bytes(), "image/png")})
    assert upload.status_code == 201

    created = client.post("/api/quick/sessions", json={
        "source_kind": "upload",
        "upload_id": upload.json()["upload_id"],
        "motion": "idle",
    })
    assert created.status_code == 201
    session = created.json()
    assert session["source_selection"] == "original"
    assert client.get(session["original_source"]).status_code == 200

    pixelized = client.post(f"/api/quick/sessions/{session['session_id']}/pixelize", json={
        "size": 64,
        "palette": "auto",
        "dither": "none",
        "background": "keep",
        "outline": "preserve",
    })
    assert pixelized.status_code == 200
    assert pixelized.json()["logical_size"] == [48, 64]
    assert pixelized.json()["subject_bbox"] == [30, 10, 67, 59]
    assert client.get(pixelized.json()["subject_source"]).status_code == 200
    assert client.get(pixelized.json()["output_source"]).status_code == 200

    selected = client.put(f"/api/quick/sessions/{session['session_id']}/source", json={"source": "pixelized"})
    assert selected.status_code == 200
    assert selected.json()["source_selection"] == "pixelized"


def test_quick_make_auto_creates_internal_run(tmp_path: Path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    upload = client.post("/api/uploads", files={"file": ("character.png", _png_bytes(), "image/png")})
    session = client.post("/api/quick/sessions", json={
        "source_kind": "upload",
        "upload_id": upload.json()["upload_id"],
    }).json()
    monkeypatch.setattr(quick_service.job_service, "start_job", lambda *_args, **_kwargs: "quick-job")

    made = client.post(f"/api/quick/sessions/{session['session_id']}/make-sprite", json={
        "motion": "idle",
        "directions": 1,
        "frames": 6,
        "sprite_source": "original",
    })
    assert made.status_code == 202
    body = made.json()
    assert body["job_id"] == "quick-job"
    assert body["run_id"].startswith("quick-")
    assert body["target_state"] == "side_idle"
    assert client.get(f"/api/runs/{body['run_id']}/assets/base-source.png").status_code == 200