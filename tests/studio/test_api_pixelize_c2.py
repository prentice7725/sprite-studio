from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from studio.api.main import app
from studio.backend import provider_service, static_service


client = TestClient(app)


def test_static_pixelize_exposes_c2_artifacts(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SPRITE_STUDIO_STATIC_ROOT", str(tmp_path / "static-projects"))

    created = client.post("/api/static", json={
        "project_id": "c2_static_demo",
        "provider": "grok",
        "asset_type": "PIXEL_SCENE",
        "description": "C2 test",
    })
    assert created.status_code == 201
    info = static_service.load_project("c2_static_demo")
    raw = info.path / "raw" / "hero.png"
    raw.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (96, 96), (40, 40, 40, 255)).save(raw)

    def fake_generate(provider: str, prompt: str, out: Path, *, refs=None, **kwargs):
        out.parent.mkdir(parents=True, exist_ok=True)
        logical = Image.new("RGBA", (64, 128), (0, 0, 0, 0))
        ImageDraw.Draw(logical).rectangle((18, 0, 45, 127), fill=(50, 110, 210, 255))
        logical.resize((512, 1024), Image.Resampling.NEAREST).save(out)
        return SimpleNamespace(to_dict=lambda: {"provider": provider, "prompt": prompt, "refs": [str(p) for p in refs or []]})

    monkeypatch.setattr(provider_service, "generate_image", fake_generate)
    response = client.post("/api/static/c2_static_demo/pixelize", json={
        "strategy": "reference_pixel_master_128",
        "asset": "hero",
        "size": 128,
        "palette": "auto",
    })

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["strategy"] == "reference_pixel_master_128"
    assert body["logical_size"][1] == 128
    for key in ("output_asset", "raw_asset", "intermediate_asset", "post_asset", "palette_asset", "profile_asset", "report_asset"):
        assert client.get(body[key]).status_code == 200
