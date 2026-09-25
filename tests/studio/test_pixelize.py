# SPDX-License-Identifier: Apache-2.0
"""Pixelize M1 deterministic engine and Static API tests."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from studio.api.main import app
from studio.backend import static_service
from studio.static_mode.pixelize import (
    PixelizeOptions,
    SUPPORTED_LOGICAL_HEIGHTS,
    pixelize_file,
    pixelize_image,
    validate_deterministic_pixel_master,
    validate_pixelize_artifacts,
)
from studio.static_mode.pixelize.engine import _border_foreground_mask


client = TestClient(app)


def _illustration(size: tuple[int, int] = (320, 240)) -> Image.Image:
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((64, 24, 256, 224), radius=42, fill=(218, 166, 126, 255), outline=(38, 31, 40, 255), width=14)
    draw.rectangle((102, 84, 218, 170), fill=(62, 99, 156, 255), outline=(28, 28, 36, 255), width=10)
    draw.ellipse((128, 46, 154, 72), fill=(30, 30, 35, 255))
    draw.ellipse((172, 46, 198, 72), fill=(30, 30, 35, 255))
    return image


def test_pixelize_target_heights_follow_the_product_contract() -> None:
    assert SUPPORTED_LOGICAL_HEIGHTS == (128, 160, 192, 256)
    for logical_height in SUPPORTED_LOGICAL_HEIGHTS:
        assert PixelizeOptions(target_size=logical_height).target_size == logical_height
    for legacy_height in (64, 96):
        with pytest.raises(ValueError, match=str(legacy_height)):
            PixelizeOptions(target_size=legacy_height)


def test_api_rejects_retired_logical_heights() -> None:
    quick = client.post("/api/quick/sessions/missing/pixelize", json={"size": 96})
    static = client.post("/api/static/missing/pixelize", json={"size": 64})

    assert quick.status_code == 422
    assert static.status_code == 422


def test_pixelize_is_deterministic_and_uses_declared_logical_size(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    _illustration().save(source)
    options = PixelizeOptions(target_size=128, palette_size=16, dither="none", background="cleanup", outline="preserve")

    first = pixelize_file(source, tmp_path / "a", options)
    second = pixelize_file(source, tmp_path / "b", options)

    assert first.logical_size == (123, 128)
    assert first.report["profile"]["target_height"] == 128
    assert first.report["profile"]["palette_scope"] == "subject"
    assert first.report["profile"]["cell_scoring"] == "area+edge+contrast+outline"
    assert first.subject_path.is_file()
    assert first.output_path.read_bytes() == second.output_path.read_bytes()
    assert first.preview_path.read_bytes() == second.preview_path.read_bytes()
    assert first.palette_path.read_text(encoding="utf-8") == second.palette_path.read_text(encoding="utf-8")
    assert first.report["validation"]["pass"] is True
    assert first.report["validation"]["metrics"]["target_height"] == 128
    assert first.report["validation"]["metrics"]["preview_matches_nearest"] is True
    assert len(first.palette) <= 16
    assert first.profile_path.is_file()
    assert first.report_path.is_file()
    assert first.preview_path.is_file()


def test_pixelize_validator_rejects_empty_subject_and_mismatched_preview(tmp_path: Path) -> None:
    invalid = validate_deterministic_pixel_master(
        Image.new("RGBA", (32, 128), (0, 0, 0, 0)),
        (),
        target_height=128,
        alpha_threshold=128,
        max_palette_size=16,
    )
    assert not invalid.pass_
    assert invalid.status == "FAIL_LOGICAL_MASTER"
    assert "subject-empty" in {warning["code"] for warning in invalid.warnings}

    source = tmp_path / "source.png"
    _illustration().save(source)
    result = pixelize_file(source, tmp_path / "artifacts", PixelizeOptions(target_size=128, palette_size=16))
    Image.new("RGBA", (4, 4), (255, 0, 0, 255)).save(result.preview_path)
    with Image.open(result.output_path) as opened:
        logical = opened.convert("RGBA")

    artifact_validation = validate_pixelize_artifacts(
        logical,
        result.palette,
        target_height=128,
        alpha_threshold=128,
        max_palette_size=16,
        output_path=result.output_path,
        preview_path=result.preview_path,
        subject_path=result.subject_path,
    )
    assert not artifact_validation.pass_
    assert "preview-mismatch" in {warning["code"] for warning in artifact_validation.warnings}


def test_pixelize_output_is_palette_locked_and_binary_alpha() -> None:
    source = _illustration((256, 256))
    logical, palette, report = pixelize_image(
        source,
        PixelizeOptions(target_size=192, palette_size=16, background="cleanup", outline="preserve"),
    )

    array = np.asarray(logical, dtype=np.uint8)
    alpha = set(int(value) for value in np.unique(array[:, :, 3]))
    opaque_colors = {tuple(int(v) for v in row[:3]) for row in array.reshape(-1, 4) if row[3] == 255}
    palette_colors = {entry[:3] for entry in palette}

    assert alpha <= {0, 255}
    assert opaque_colors <= palette_colors
    assert report["profile"]["color_space"] == "oklab"
    assert report["profile"]["downsample_mode"] == "dominant-cell"


def test_opaque_subject_cleanup_scales_foreground_not_detector_padding() -> None:
    source = Image.new("RGB", (96, 128), (0, 255, 0))
    draw = ImageDraw.Draw(source)
    draw.ellipse((32, 10, 64, 42), fill=(244, 202, 160))
    draw.rectangle((26, 40, 70, 104), fill=(45, 80, 140))
    draw.line((48, 52, 48, 120), fill=(28, 24, 30), width=3)

    logical, _, report = pixelize_image(
        source,
        PixelizeOptions(target_size=128, palette_size=16, background="cleanup"),
    )

    assert logical.height == 128
    assert report["validation"]["pass"] is True
    assert report["validation"]["metrics"]["subject_height"] == 128
    assert report["subject_bbox"] == [26, 10, 71, 121]


def test_border_connected_green_spill_is_removed_but_enclosed_green_detail_survives() -> None:
    source = Image.new("RGBA", (96, 96), (0, 255, 0, 255))
    draw = ImageDraw.Draw(source)
    draw.ellipse((12, 12, 84, 84), fill=(30, 220, 30, 255))
    draw.ellipse((18, 18, 78, 78), fill=(232, 194, 156, 255))
    draw.point((18, 48), fill=(128, 255, 128, 255))
    draw.ellipse((42, 38, 50, 46), fill=(40, 150, 60, 255))
    draw.ellipse((60, 38, 68, 46), fill=(0, 180, 0, 255))

    mask = _border_foreground_mask(np.asarray(source, dtype=np.uint8), 128)

    assert not mask[12, 48]  # screen-coloured fringe joins the outer green field
    assert not mask[48, 18]  # pale one-pixel spill is adjacent to the screen field
    assert mask[42, 46]  # enclosed green detail differs from the screen chroma
    assert not mask[42, 64]  # exact screen-hue detail is indistinguishable from spill


def test_key_coloured_edge_spill_next_to_transparency_is_removed() -> None:
    source = Image.new("RGBA", (96, 96), (0, 255, 0, 255))
    draw = ImageDraw.Draw(source)
    draw.ellipse((12, 12, 84, 84), fill=(232, 194, 156, 255))
    source.putpixel((45, 48), (0, 0, 0, 0))
    source.putpixel((46, 48), (128, 255, 128, 255))

    mask = _border_foreground_mask(np.asarray(source, dtype=np.uint8), 128)

    assert not mask[48, 46]


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
    assert body["logical_size"] == [123, 128]
    assert body["subject_bbox"][:2] == [64, 24]
    assert body["subject_bbox"][2] >= 256 and body["subject_bbox"][3] >= 224
    assert client.get(body["subject_asset"]).status_code == 200
    assert body["palette_size"] <= 24
    for key in ("output_asset", "preview_asset", "palette_asset", "profile_asset", "report_asset"):
        assert client.get(body[key]).status_code == 200


def test_pixelize_api_rejects_missing_raw_asset(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SPRITE_STUDIO_STATIC_ROOT", str(tmp_path / "static-projects"))
    client.post("/api/static", json={"project_id": "empty_demo", "provider": "grok", "description": "scene"})

    response = client.post("/api/static/empty_demo/pixelize", json={"asset": "missing", "size": 128, "palette": "auto"})

    assert response.status_code == 400
    assert "no raw asset to pixelize" in response.json()["detail"]

def test_manual_subject_crop_scales_character_height_and_keeps_features() -> None:
    source = _illustration((320, 240))
    logical, palette, report = pixelize_image(
        source,
        PixelizeOptions(
            target_size=128,
            palette_size=16,
            subject_mode="manual",
            subject_bbox=(64, 24, 256, 224),
            detail="detailed",
            outline="preserve",
        ),
    )

    assert logical.size == (123, 128)
    assert palette
    assert report["subject_bbox"] == [64, 24, 256, 224]
    assert report["profile"]["thin_feature_recovery"] is True
    assert report["profile"]["palette_scope"] == "subject"
