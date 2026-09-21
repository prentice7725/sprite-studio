from __future__ import annotations

import io
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from studio.api.main import app
from studio.api.contracts import QuickMakeSpriteRequest
from studio.api.uploads import UPLOADS_ROOT_ENV
from studio.backend import provider_service, quick_service
from studio.backend.run_manager import RUNS_ROOT_ENV


client = TestClient(app)


def test_quick_make_contract_separates_pixel_master_and_generation_strategies() -> None:
    request = QuickMakeSpriteRequest(pixelize=True)
    assert request.strategy == "reference_pixel_master_128"
    assert request.generation_strategy == "AUTO"
    assert "strategy" not in QuickMakeSpriteRequest.model_fields or list(QuickMakeSpriteRequest.model_fields).count("strategy") == 1


def _source_bytes() -> bytes:
    image = Image.new("RGBA", (96, 96), (255, 0, 255, 255))
    ImageDraw.Draw(image).rectangle((24, 12, 71, 83), fill=(60, 110, 210, 255))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_quick_c2_is_first_class_and_keeps_all_artifacts(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv(RUNS_ROOT_ENV, str(tmp_path / "runs"))
    monkeypatch.setenv(UPLOADS_ROOT_ENV, str(tmp_path / "uploads"))
    monkeypatch.setenv(quick_service.QUICK_ROOT_ENV, str(tmp_path / "quick"))

    def fake_generate(provider: str, prompt: str, out: Path, *, refs=None, **kwargs):
        out.parent.mkdir(parents=True, exist_ok=True)
        logical = Image.new("RGBA", (64, 128), (0, 0, 0, 0))
        ImageDraw.Draw(logical).rectangle((18, 0, 45, 127), fill=(50, 110, 210, 255))
        logical.resize((512, 1024), Image.Resampling.NEAREST).save(out)
        return SimpleNamespace(to_dict=lambda: {"provider": provider, "prompt": prompt, "refs": [str(p) for p in refs or []]})

    monkeypatch.setattr(provider_service, "generate_image", fake_generate)
    upload = client.post("/api/uploads", files={"file": ("character.png", _source_bytes(), "image/png")})
    session = client.post("/api/quick/sessions", json={
        "source_kind": "upload",
        "upload_id": upload.json()["upload_id"],
        "provider": "grok",
    }).json()

    response = client.post(f"/api/quick/sessions/{session['session_id']}/pixelize", json={
        "strategy": "reference_pixel_master_128",
        "size": 128,
        "palette": "auto",
    })

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["strategy"] == "reference_pixel_master_128"
    assert body["logical_size"][1] == 128
    for key in ("output_source", "raw_source", "intermediate_source", "post_source"):
        assert client.get(body[key]).status_code == 200
    assert body["report"]["strategy"] == "reference_pixel_master_128"

    selected = client.put(f"/api/quick/sessions/{session['session_id']}/source", json={"source": "pixelized"})
    assert selected.status_code == 200, selected.text
    assert selected.json()["source_selection"] == "pixelized"
