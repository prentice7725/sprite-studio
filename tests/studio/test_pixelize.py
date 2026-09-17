# SPDX-License-Identifier: Apache-2.0
"""Pixelize M1 deterministic engine and Static API tests."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from studio.api.main import app
from studio.backend import static_service
from studio.static_mode.pixelize import PixelizeOptions, pixelize_file, pixelize_image


client = TestClient(app)


def _illustration(size: tuple[int, int] = (320, 240)) -> Image.Image:
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((64, 24, 256, 224), radius=42, fill=(218, 166, 126, 255), outline=(38, 31, 40, 255), width=14)
    draw.rectangle((102, 84, 218, 170), fill=(62, 99, 156, 255), outline=(28, 28, 36, 255), width=10)
    draw.ellipse((128, 46, 154, 72), fill=(30, 30, 35, 255))
    draw.ellipse((172, 46, 198, 72), fill=(30, 30, 35, 255))
    return image


def test_pixelize_is_deterministic_and_uses_declared_logical_size(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    _illustration().save(source)
    options = PixelizeOptions(target_size=96, palette_size=16, dither="none", background="cleanup", outline="preserve")

    first = pixelize_file(source, tmp_path / "a", options)
    second = pixelize_file(source, tmp_path / "b", options)

    assert first.logical_size == (96, 72)
    assert first.output_path.read_bytes() == second.output_path.read_bytes()
    assert first.palette_path.read_text(encoding="utf-8") == second.palette_path.read_text(encoding="utf-8")
    assert len(first.palette) <= 16
    assert first.profile_path.is_file()
    assert first.report_path.is_file()
    assert first.preview_path.is_file()


def test_pixelize_output_is_palette_locked_and_binary_alpha() -> None:
    source = _illustration((256, 256))
    logical, palette, report = pixelize_image(
        source,
        PixelizeOptions(target_size=64, palette_size=16, background="cleanup", outline="preserve"),
    )

    array = np.asarray(logical, dtype=np.uint8)
    alpha = set(int(value) for value in np.unique(array[:, :, 3]))
    opaque_colors = {tuple(int(v) for v in row[:3]) for row in array.reshape(-1, 4) if row[3] == 255}
    palette_colors = {entry[:3] for entry in palette}

    assert alpha <= {0, 255}
    assert opaque_colors <= palette_colors
    assert report["profile"]["color_space"] == "oklab"
    assert report["profile"]["downsample_mode"] == "dominant-cell"


def test_pixelize_api_persists_profile_palette_and_preview(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SPRITE_STUDIO_STATIC_ROOT", str(tmp_path / "static-projects"))
    created = client.post("/api/static", json={
        "project_id": "portrait_demo",
        "provider": "grok",
        "asset_type": "PIXEL_SCENE",
        "description": "A character illustration for Pixelize M1.",
    })
    assert created.status_code == 201

    info = static_service.load_project("portrait_demo")
    raw = info.path / "raw" / "hero.png"
    raw.parent.mkdir(parents=True, exist_ok=True)
    _illustration().save(raw)

    response = client.post("/api/static/portrait_demo/pixelize", json={
        "asset": "hero",
        "size": 128,
        "palette": 24,
        "dither": "none",
        "background": "cleanup",
        "outline": "preserve",
    })

    assert response.status_code == 200
    body = response.json()
    assert body["logical_size"] == [128, 96]
    assert body["palette_size"] <= 24
    for key in ("output_asset", "preview_asset", "palette_asset", "profile_asset", "report_asset"):
        assert client.get(body[key]).status_code == 200


def test_pixelize_api_rejects_missing_raw_asset(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SPRITE_STUDIO_STATIC_ROOT", str(tmp_path / "static-projects"))
    client.post("/api/static", json={"project_id": "empty_demo", "provider": "grok", "description": "scene"})

    response = client.post("/api/static/empty_demo/pixelize", json={"asset": "missing", "size": 128, "palette": "auto"})

    assert response.status_code == 400
    assert "no raw asset to pixelize" in response.json()["detail"]
