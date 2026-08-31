# SPDX-License-Identifier: Apache-2.0
"""Static Mode project lifecycle and mode dispatch (spec §13, §16)."""

from __future__ import annotations

import json

import numpy as np
import pytest
from PIL import Image

from studio.backend import static_service
from studio.backend.preset_service import list_presets, list_static_presets, load_preset, load_static_preset
from studio.backend.schemas import StaticProjectConfig, StudioRunConfig


@pytest.fixture()
def static_root(tmp_path, monkeypatch):
    monkeypatch.setenv("SPRITE_STUDIO_STATIC_ROOT", str(tmp_path))
    return tmp_path


def _scene(size: int = 32, pitch: int = 8, *, seed: int = 3, tileable: bool = False) -> Image.Image:
    rng = np.random.default_rng(seed)
    palette = rng.integers(20, 235, (12, 3), dtype=np.uint8)
    index = rng.integers(0, 12, (size, size))
    if tileable:
        index[:, -1] = index[:, 0]
        index[-1, :] = index[0, :]
    rgb = palette[index]
    truth = Image.fromarray(
        np.dstack([rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2], np.full((size, size), 255, np.uint8)]), "RGBA"
    )
    return truth.resize((size * pitch, size * pitch), Image.Resampling.NEAREST)


def _project(static_root, **kwargs) -> tuple:
    config = StaticProjectConfig(project_id=kwargs.pop("project_id", "scene_001"), provider="grok", **kwargs)
    info = static_service.create_project(config)
    source = static_root / "source.png"
    _scene(tileable=kwargs.get("tileable", False)).save(source)
    static_service.import_asset(info, source, asset="scene")
    return info, source


def test_create_project_writes_the_declared_contract(static_root) -> None:
    info, _ = _project(static_root, asset_type="tile_set", tileable=True, export_size=(512, 512))
    payload = json.loads((info.path / "static" / "project.json").read_text(encoding="utf-8"))
    assert payload["mode"] == "static"
    assert payload["config"]["asset_type"] == "TILE_SET"
    assert info.asset_type == "TILE_SET" and info.tileable is True
    assert static_service.load_project("scene_001").export_size == (512, 512)


def test_project_ids_are_validated_and_not_overwritten(static_root) -> None:
    with pytest.raises(ValueError, match="project_id"):
        static_service.create_project(StaticProjectConfig(project_id="../escape", provider="grok"))
    _project(static_root)
    with pytest.raises(FileExistsError):
        static_service.create_project(StaticProjectConfig(project_id="scene_001", provider="grok"))


def test_full_static_pipeline_produces_every_artifact(static_root) -> None:
    info, _ = _project(static_root, asset_type="tile_set", tileable=True, export_size=(256, 256),
                       refine={"seam_check": True})
    report = static_service.refine_asset(info, "scene")
    assert report["kind"] == "asset-studio-static-refine"
    assert report["grid"]["locked"]
    seam = static_service.check_tileability(info, "scene", repair=True)
    layers = static_service.process_layers(info, "scene")
    qa = static_service.static_qa(info, "scene")
    exported = static_service.export_asset(info, "scene")

    assert seam["repair"]["after"]["ok"]
    assert layers["round_trips"] is True
    assert qa["kind"] == "asset-studio-static-qa"
    assert exported.is_file()
    with Image.open(exported) as image:
        assert image.size == (256, 256)
    assert static_service.project_status(info)["scene"] == "exported"


def test_export_uses_nearest_only(static_root) -> None:
    """A smooth filter at export undoes the entire refine stage at the last step."""
    info, _ = _project(static_root, export_size=(128, 128))
    static_service.refine_asset(info, "scene")
    logical = static_service.refined_image(info, "scene")
    exported_path = static_service.export_asset(info, "scene")
    manifest = json.loads((info.path / "export" / "scene.manifest.json").read_text(encoding="utf-8"))
    assert manifest["resample"] == "nearest"
    with Image.open(exported_path) as exported:
        expected = logical.resize((128, 128), Image.Resampling.NEAREST)
        assert np.array_equal(np.asarray(exported.convert("RGBA")), np.asarray(expected))


def test_project_overrides_reach_the_refine_engine(static_root) -> None:
    info, _ = _project(static_root, refine={"dither_mode": "ordered", "palette_colors": 8})
    report = static_service.refine_asset(info, "scene")
    assert report["palette"]["dither"] == "ordered"
    assert report["settings"]["palette"]["colors"] == 8


def test_refine_without_a_raw_asset_fails_loudly(static_root) -> None:
    info = static_service.create_project(StaticProjectConfig(project_id="empty_001", provider="grok"))
    with pytest.raises(FileNotFoundError, match="no raw asset"):
        static_service.refine_asset(info, "scene")


def test_the_two_project_contracts_refuse_each_others_mode() -> None:
    """A tile set must not be able to inherit character animation semantics."""
    with pytest.raises(ValueError, match="Sprite Mode contract"):
        StudioRunConfig(
            run_id="x", character_id="x", provider="grok", base_image=None,
            directions=("side",), mirrors={}, states={"idle": {"frames": 4}}, mode="static",
        )
    with pytest.raises(ValueError, match="Static Mode contract"):
        StaticProjectConfig(project_id="x", provider="grok", mode="sprite")


def test_static_project_rejects_an_unknown_asset_type() -> None:
    with pytest.raises(ValueError, match="not valid for"):
        StaticProjectConfig(project_id="x", provider="grok", asset_type="CHARACTER")


def test_presets_are_separated_by_mode() -> None:
    """A UI must not be able to offer a tile-set preset to a character run."""
    sprite = set(list_presets())
    static = set(list_static_presets())
    assert "sword" in sprite and "sword" not in static
    assert "tile_set" in static and "tile_set" not in sprite
    assert load_static_preset("tile_set")["asset_type"] == "TILE_SET"
    assert "directions" in load_preset("sword")
    with pytest.raises(ValueError, match="unknown preset"):
        load_static_preset("sword")


def test_cleanup_asset_runs_without_re_deciding_the_grid(static_root) -> None:
    """CLEANUP is its own stage (spec §12.3): tuning a speck threshold must not
    re-run the grid search and move the lattice under the operator."""
    info, _ = _project(static_root)
    refined = static_service.refine_asset(info, "scene", cleanup=False)
    grid_before = refined["grid"]

    image = static_service.refined_image(info, "scene")
    image.putpixel((0, 0), (255, 0, 0, 255))
    image.save(info.path / "refined" / "scene.png")

    report = static_service.cleanup_asset(info, "scene", orphan_max_area=2)
    assert report["kind"] == "asset-studio-static-cleanup"
    assert report["orphan_max_area"] == 2
    assert (info.path / "qa" / "scene.cleanup.json").is_file()
    # The stored refine report — and therefore the grid decision — is untouched.
    stored = json.loads((info.path / "refined" / "scene.report.json").read_text(encoding="utf-8"))
    assert stored["grid"] == grid_before


def test_cleanup_honours_the_orphan_threshold_it_is_given(static_root) -> None:
    info, _ = _project(static_root)
    static_service.refine_asset(info, "scene", cleanup=False)
    image = static_service.refined_image(info, "scene")
    width, height = image.size
    # A lone speck clear of the scene, on a transparent margin we add for it.
    padded = Image.new("RGBA", (width + 4, height + 4), (0, 0, 0, 0))
    padded.alpha_composite(image, (0, 0))
    padded.putpixel((width + 2, height + 2), (255, 0, 0, 255))
    padded.save(info.path / "refined" / "scene.png")

    static_service.cleanup_asset(info, "scene", orphan_max_area=1)
    assert np.asarray(static_service.refined_image(info, "scene"))[height + 2, width + 2, 3] == 0
