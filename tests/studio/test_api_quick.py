# SPDX-License-Identifier: Apache-2.0
"""Quick Generate source-first API contract tests."""

from __future__ import annotations

import io
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from studio.api.main import app
from studio.api.contracts import QuickMakeSpriteRequest, QuickPixelizeRequest
from studio.api.uploads import UPLOADS_ROOT_ENV
from studio.backend import quick_service, static_service
from studio.backend.run_manager import RUNS_ROOT_ENV
from studio.static_mode.pixelize import engine as pixelize_engine
from studio.static_mode.pixelize.validation import PixelMasterValidation


client = TestClient(app)


def test_quick_pixel_master_defaults_to_the_deterministic_path() -> None:
    assert QuickPixelizeRequest().size == 128
    assert QuickMakeSpriteRequest(pixelize=True).pixelize
    assert QuickPixelizeRequest().strategy == "preserve"
    assert QuickMakeSpriteRequest(pixelize=True).strategy == "preserve"


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
        "size": 128,
        "palette": "auto",
        "dither": "none",
        "background": "keep",
        "outline": "preserve",
    })
    assert pixelized.status_code == 200
    assert pixelized.json()["strategy"] == "preserve"
    assert pixelized.json()["accepted"] == "logical_master"
    assert pixelized.json()["logical_size"] == [97, 128]
    assert pixelized.json()["subject_bbox"] == [30, 10, 67, 59]
    assert client.get(pixelized.json()["subject_source"]).status_code == 200
    assert client.get(pixelized.json()["output_source"]).status_code == 200

    selected = client.put(f"/api/quick/sessions/{session['session_id']}/source", json={"source": "pixelized"})
    assert selected.status_code == 200
    assert selected.json()["source_selection"] == "pixelized"


def test_quick_and_static_preserve_adapters_produce_the_same_logical_master(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setenv("SPRITE_STUDIO_STATIC_ROOT", str(tmp_path / "static-projects"))

    source_bytes = _png_bytes()
    upload = client.post(
        "/api/uploads",
        files={"file": ("character.png", source_bytes, "image/png")},
    )
    assert upload.status_code == 201
    session = client.post("/api/quick/sessions", json={
        "source_kind": "upload",
        "upload_id": upload.json()["upload_id"],
        "motion": "idle",
    }).json()

    quick = client.post(f"/api/quick/sessions/{session['session_id']}/pixelize", json={
        "size": 128,
        "palette": 16,
        "dither": "none",
        "background": "keep",
        "outline": "preserve",
        "subject_mode": "auto",
        "detail": "balanced",
        "alpha_threshold": 128,
    })
    assert quick.status_code == 200, quick.text

    created = client.post("/api/static", json={
        "project_id": "parity_demo",
        "provider": "grok",
        "asset_type": "PIXEL_SCENE",
        "description": "Pixel master adapter parity fixture.",
    })
    assert created.status_code == 201, created.text
    info = static_service.load_project("parity_demo")
    raw = info.path / "raw" / "hero.png"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_bytes(source_bytes)

    static = client.post("/api/static/parity_demo/pixelize", json={
        "asset": "hero",
        "size": 128,
        "palette": 16,
        "dither": "none",
        "background": "keep",
        "outline": "preserve",
        "subject_mode": "auto",
        "detail": "balanced",
        "alpha_threshold": 128,
    })
    assert static.status_code == 200, static.text

    quick_body = quick.json()
    static_body = static.json()
    assert quick_body["logical_size"] == static_body["logical_size"]
    assert quick_body["accepted"] == "logical_master"
    assert static_body["accepted"] == "logical_master"
    assert quick_body["subject_bbox"] == static_body["subject_bbox"]
    assert client.get(quick_body["output_source"]).content == client.get(static_body["output_asset"]).content


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


def test_quick_make_pixelize_uses_the_preserve_logical_master(tmp_path: Path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    upload = client.post("/api/uploads", files={"file": ("character.png", _png_bytes(), "image/png")})
    session = client.post("/api/quick/sessions", json={
        "source_kind": "upload",
        "upload_id": upload.json()["upload_id"],
    }).json()
    monkeypatch.setattr(quick_service.job_service, "start_job", lambda *_args, **_kwargs: "quick-pixel-job")

    made = client.post(f"/api/quick/sessions/{session['session_id']}/make-sprite", json={
        "pixelize": True,
        "pixel_size": 128,
        "sprite_source": "pixelized",
    })

    assert made.status_code == 202, made.text
    migrated = quick_service.load_session(session["session_id"])
    assert migrated["pixelize_strategy"] == "preserve"
    assert migrated["pixelize_accepted"] == "logical_master"
    master_url = made.json()["session"]["pixelized_source"]
    master_response = client.get(master_url)
    assert master_response.status_code == 200
    with Image.open(io.BytesIO(master_response.content)) as master:
        assert master.size == (97, 128)


def test_legacy_semantic_master_requires_preserve_rerun_or_original_source(tmp_path: Path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    upload = client.post("/api/uploads", files={"file": ("character.png", _png_bytes(), "image/png")})
    session = client.post("/api/quick/sessions", json={
        "source_kind": "upload",
        "upload_id": upload.json()["upload_id"],
    }).json()

    payload = quick_service.load_session(session["session_id"])
    legacy_path = quick_service._session_dir(session["session_id"]) / "pixelized" / "post" / "master.png"
    legacy_path.parent.mkdir(parents=True)
    Image.new("RGBA", (128, 128), (20, 30, 40, 255)).save(legacy_path)
    payload.update({
        "source_selection": "pixelized",
        "pixelized_source": "pixelized/post/master.png",
        "pixelize_strategy": "reference_pixel_master_128",
    })
    quick_service._write(session["session_id"], payload)

    rejected = client.put(
        f"/api/quick/sessions/{session['session_id']}/source",
        json={"source": "pixelized"},
    )
    assert rejected.status_code == 400
    assert "rerun deterministic Preserve Pixelize" in rejected.json()["detail"]

    made = client.post(f"/api/quick/sessions/{session['session_id']}/make-sprite", json={
        "sprite_source": "pixelized",
    })
    assert made.status_code == 409
    assert "choose the original source" in made.json()["detail"]

    preserve = client.post(f"/api/quick/sessions/{session['session_id']}/pixelize", json={"size": 128})
    assert preserve.status_code == 200, preserve.text
    migrated = quick_service.load_session(session["session_id"])
    assert migrated["pixelize_strategy"] == "preserve"
    assert migrated["pixelize_accepted"] == "logical_master"
    assert legacy_path.is_file(), "migration must preserve the legacy semantic artifact"


def test_failed_logical_master_validation_is_not_accepted(tmp_path: Path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    upload = client.post("/api/uploads", files={"file": ("character.png", _png_bytes(), "image/png")})
    session = client.post("/api/quick/sessions", json={
        "source_kind": "upload",
        "upload_id": upload.json()["upload_id"],
    }).json()

    def fail_validation(*_args, **_kwargs):
        return PixelMasterValidation(
            False,
            "FAIL_LOGICAL_MASTER",
            {"logical_size": [97, 128]},
            ({"code": "test-invalid", "message": "forced test failure"},),
        )

    monkeypatch.setattr(pixelize_engine, "validate_pixelize_artifacts", fail_validation)
    failed = client.post(f"/api/quick/sessions/{session['session_id']}/pixelize", json={"size": 128})
    assert failed.status_code == 400
    assert "validation failed" in failed.json()["detail"]

    payload = quick_service.load_session(session["session_id"])
    assert payload["pixelize_accepted"] == "validation_failed"
    assert payload["pixelize_validation"]["pass"] is False
    rejected = client.post(f"/api/quick/sessions/{session['session_id']}/make-sprite", json={
        "sprite_source": "pixelized",
    })
    assert rejected.status_code == 409
    assert "failed validation" in rejected.json()["detail"]


def test_prompt_source_creation_is_retired() -> None:
    response = client.post("/api/quick/sessions", json={
        "source_kind": "prompt",
        "prompt": "a knight",
    })
    assert response.status_code == 422
