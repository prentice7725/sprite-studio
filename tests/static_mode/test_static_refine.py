# SPDX-License-Identifier: MIT
"""Static Refine Engine v0.2 and Static Mode pipeline contracts (spec §7, §8)."""

from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from studio.shared.config import apply_overrides, load_refine_settings
from studio.static_mode.cleanup import cleanup_scene, fill_holes, remove_orphans
from studio.static_mode.layer import compose_layers, cutout_object, split_layers
from studio.static_mode.prompt import StaticPromptAssembler, StaticPromptValidator
from studio.static_mode.qa import run_static_qa
from studio.static_mode.refine import (
    StaticRefineEngine,
    apply_dither,
    candidate_periods,
    crop_to_grid,
    detect_scene_grid,
    propose_cell_sizes,
)
from studio.static_mode.tile import check_seams, repair_seams, wraparound_preview


PITCH = 8


def _truth(size: int = 32, *, colors: int = 12, seed: int = 3, tileable: bool = False) -> Image.Image:
    rng = np.random.default_rng(seed)
    palette = rng.integers(20, 235, (colors, 3), dtype=np.uint8)
    index = rng.integers(0, colors, (size, size))
    if tileable:
        index[:, -1] = index[:, 0]
        index[-1, :] = index[0, :]
    rgb = palette[index]
    return Image.fromarray(
        np.dstack([rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2], np.full((size, size), 255, np.uint8)]), "RGBA"
    )


def _upscaled(truth: Image.Image, pitch: int = PITCH) -> Image.Image:
    return truth.resize((truth.width * pitch, truth.height * pitch), Image.Resampling.NEAREST)


def _settings():
    return load_refine_settings("static")


def test_static_refine_recovers_the_ground_truth_exactly() -> None:
    """The end-to-end claim: a clean upscale must come back byte-identical."""
    truth = _truth()
    output = StaticRefineEngine(_settings()).refine(_upscaled(truth), asset_type="PIXEL_SCENE", cleanup=False)
    assert output.logical.size == truth.size
    assert np.array_equal(np.asarray(output.logical), np.asarray(truth))
    assert output.grid.pitch[0] == pytest.approx(PITCH, abs=1e-6)


def test_fft_proposes_the_true_period_but_does_not_decide_it() -> None:
    settings = _settings()
    scene = _upscaled(_truth())
    candidates = propose_cell_sizes(scene, settings.fft, settings.lattice)
    assert candidates
    assert any(abs(period - PITCH) < 0.5 for period in candidate_periods(candidates))
    # A deliberately wrong proposal must not be able to pick the grid.
    poisoned = detect_scene_grid(scene, settings.lattice, proposals=[37.0])
    assert poisoned.pitch[0] == pytest.approx(PITCH, abs=0.2)


def test_fft_candidate_search_is_opt_out() -> None:
    settings = apply_overrides(_settings(), {"fft_candidate_search": False})
    assert propose_cell_sizes(_upscaled(_truth()), settings.fft, settings.lattice) == []


def test_large_image_takes_the_coarse_to_fine_path() -> None:
    settings = _settings()
    big = _upscaled(_truth(size=64), pitch=8)  # 512x512 = 262144 px
    grid = detect_scene_grid(big, settings.lattice)
    assert grid.coarse_to_fine is True
    assert grid.pitch[0] == pytest.approx(PITCH, abs=0.2)


def test_unlocked_grid_passes_through_and_says_so() -> None:
    settings = apply_overrides(_settings(), {"grid": {"confidence_floor": 0.99}})
    flat = Image.new("RGBA", (64, 64), (120, 90, 60, 255))
    output = StaticRefineEngine(settings).refine(flat, cleanup=False)
    assert not output.grid.locked
    assert any(warning["code"] == "grid-unlocked" for warning in output.report["warnings"])


def test_dither_is_off_by_default_and_never_reaches_sprite_mode() -> None:
    """§8.4: dither is a Static-only decision, and OFF unless asked for."""
    assert _settings().dither.mode == "off"
    assert not hasattr(load_refine_settings("sprite"), "dither_module")
    with pytest.raises(ImportError):
        __import__("studio.sprite_mode.refine.dither")


def test_ordered_and_serpentine_dither_stay_inside_the_palette() -> None:
    scene = _truth(size=16, colors=8)
    palette = ((10, 10, 10, 255), (250, 250, 250, 255), (200, 40, 40, 255))
    for mode in ("ordered", "serpentine"):
        settings = apply_overrides(_settings(), {"dither_mode": mode}).dither
        result = np.asarray(apply_dither(scene, palette, settings))
        opaque = result[result[:, :, 3] >= 128][:, :3]
        used = {tuple(int(value) for value in color) for color in np.unique(opaque, axis=0)}
        assert used <= {entry[:3] for entry in palette}


def test_unknown_dither_mode_is_an_error() -> None:
    settings = apply_overrides(_settings(), {"dither_mode": "diffuse-ish"}).dither
    with pytest.raises(ValueError, match="dither.mode"):
        apply_dither(_truth(size=8), ((0, 0, 0, 255),), settings)


def test_seam_check_detects_an_open_tile_and_repair_closes_it() -> None:
    settings = apply_overrides(_settings(), {"seam_check": True}).seam
    gradient = np.tile(np.linspace(20, 240, 32, dtype=np.uint8), (32, 1))
    tile = Image.fromarray(
        np.dstack([gradient, np.full((32, 32), 100, np.uint8), np.full((32, 32), 150, np.uint8),
                   np.full((32, 32), 255, np.uint8)]), "RGBA")
    before = check_seams(tile, settings)
    assert not before.ok and before.horizontal > settings.threshold
    repaired, detail = repair_seams(tile, settings)
    assert detail["after"]["ok"]
    assert check_seams(repaired, settings).horizontal < before.horizontal


def test_seam_check_treats_an_alpha_discontinuity_as_a_seam() -> None:
    """A colour-only metric scores an opaque edge meeting a transparent one as perfect."""
    settings = apply_overrides(_settings(), {"seam_check": True}).seam
    array = np.zeros((16, 16, 4), dtype=np.uint8)
    array[:, :, :3] = 80
    array[:, :, 3] = 255
    array[:, -1, 3] = 0
    assert not check_seams(Image.fromarray(array, "RGBA"), settings).ok


def test_a_tileable_truth_passes_its_own_seam_check() -> None:
    settings = apply_overrides(_settings(), {"seam_check": True}).seam
    assert check_seams(_truth(tileable=True), settings).ok


def test_wraparound_preview_offsets_alternate_rows() -> None:
    tile = _truth(size=16)
    preview = wraparound_preview(tile, repeat=2)
    assert preview.size == (32, 32)


def test_crop_to_grid_trims_to_whole_cells() -> None:
    """A partial trailing cell is what makes a wrapped tile edge land half a block off.

    "Whole cells" is measured against the *detected* pitch, which is fractional
    by design — the block width of generated art is 8.14px as readily as 8.00.
    """
    settings = _settings()
    scene = _upscaled(_truth(size=16))
    grid = detect_scene_grid(scene, settings.lattice)
    cropped, offset = crop_to_grid(scene, grid)
    assert offset[0] >= 0 and offset[1] >= 0
    assert cropped.width <= scene.width and cropped.height <= scene.height
    for extent, pitch in ((cropped.width, grid.pitch[0]), (cropped.height, grid.pitch[1])):
        cells = extent / pitch
        assert cells == pytest.approx(round(cells), abs=0.5 / pitch + 1e-9)


def test_cleanup_removes_specks_and_fills_enclosed_holes_only() -> None:
    settings = _settings().cleanup
    image = Image.new("RGBA", (40, 40), (0, 0, 0, 0))
    image.paste((90, 140, 70, 255), (8, 8, 32, 32))
    image.putpixel((3, 3), (200, 0, 0, 255))
    image.putpixel((20, 20), (0, 0, 0, 0))
    result = cleanup_scene(image, settings)
    array = np.asarray(result.image)
    assert array[3, 3, 3] == 0
    assert tuple(array[20, 20]) == (90, 140, 70, 255)
    # The surrounding transparent background reaches the border and must survive.
    assert array[0, 0, 3] == 0


def test_orphan_removal_respects_the_configured_area() -> None:
    settings = _settings().cleanup
    image = Image.new("RGBA", (20, 20), (0, 0, 0, 0))
    image.paste((10, 10, 10, 255), (2, 2, 4, 4))  # 2x2 = 4 px, above the default max of 2
    image.putpixel((15, 15), (10, 10, 10, 255))  # 1 px, below it
    array = np.asarray(remove_orphans(image, settings).image)
    assert array[15, 15, 3] == 0
    assert array[2, 2, 3] == 255


def test_hole_fill_leaves_a_border_connected_region_alone() -> None:
    image = Image.new("RGBA", (12, 12), (0, 0, 0, 0))
    image.paste((50, 60, 70, 255), (0, 0, 12, 6))
    array = np.asarray(fill_holes(image).image)
    assert array[9, 5, 3] == 0


def test_layer_split_round_trips_to_the_input() -> None:
    """A split that does not recompose has dropped or duplicated pixels."""
    scene = Image.new("RGBA", (32, 32), (30, 40, 90, 255))
    scene.paste((160, 120, 40, 255), (6, 18, 26, 32))
    scene.paste((220, 40, 40, 255), (14, 8, 18, 14))
    layers, report = split_layers(scene)
    assert report["layers"]
    recomposed = compose_layers(layers, scene.size)
    assert np.array_equal(np.asarray(recomposed), np.asarray(scene))


def test_cutout_keeps_an_enclosed_background_coloured_detail() -> None:
    """A sky-coloured window inside the object is part of the object."""
    scene = Image.new("RGBA", (24, 24), (40, 90, 200, 255))
    scene.paste((150, 110, 60, 255), (6, 6, 18, 18))
    scene.paste((40, 90, 200, 255), (10, 10, 13, 13))  # window, same colour as sky
    result, report = cutout_object(scene)
    array = np.asarray(result)
    assert array[0, 0, 3] == 0
    assert array[11, 11, 3] == 255
    assert report["kept_pixels"] > 0


def test_static_qa_flags_soft_edges_and_open_seams() -> None:
    settings = apply_overrides(_settings(), {"seam_check": True})
    array = np.zeros((16, 16, 4), dtype=np.uint8)
    array[:, :, :3] = 80
    array[:, :, 3] = 255
    array[0, :, :3] = 240
    array[4, 4, 3] = 90
    image = Image.fromarray(array, "RGBA")
    result = run_static_qa(image, settings, asset_type="TILE_SET", tileable=True)
    codes = {warning["code"] for warning in result.warnings}
    assert "seam-open" in codes
    assert not result.ok


def test_static_prompt_validator_rejects_sprite_shaped_requirements() -> None:
    """The reason Static has its own validator: a tile has no body to show fully."""
    validator = StaticPromptValidator()
    tile_prompt = StaticPromptAssembler().assemble(
        "p", "muddy ground", asset_type="tile_set", tileable=True
    ).final_prompt
    assert validator.validate(tile_prompt, asset_type="TILE_SET", tileable=True) == []
    bare = "a nice muddy field with soft lighting"
    codes = {issue.code for issue in validator.validate(bare, asset_type="TILE_SET", tileable=True)}
    assert {"FLAT_REGIONS_MISSING", "SOFTNESS_NOT_BANNED", "TILEABILITY_MISSING"} <= codes


def test_static_prompts_are_clean_for_every_asset_type() -> None:
    assembler = StaticPromptAssembler()
    for asset_type, tileable in (("pixel_scene", False), ("tile_set", True), ("prop_object", False), ("flat_scene", False)):
        result = assembler.assemble("p", "a test asset", asset_type=asset_type, tileable=tileable)
        assert [issue for issue in result.issues if issue.severity == "error"] == []


def test_sprite_settings_are_refused_by_the_static_engine() -> None:
    with pytest.raises(ValueError, match="static settings"):
        StaticRefineEngine(load_refine_settings("sprite"))


def test_tile_align_trims_in_source_space_not_logical_space() -> None:
    """Regression: the whole-cell trim must happen before the snap.

    Cropping the logical output with a source-space pitch cuts in the wrong
    place on any fractional pitch — and most detected pitches are fractional.
    A 129px scene at pitch ~8.1 has a partial trailing cell that must be gone
    from the source, leaving a logical output with no half-block edge.
    """
    settings = _settings()
    truth = _truth(size=16)
    scene = _upscaled(truth).crop((0, 0, 129, 129))
    engine = StaticRefineEngine(settings)
    plain = engine.refine(scene, asset_type="TILE_SET", cleanup=False)
    aligned = engine.refine(scene, asset_type="TILE_SET", cleanup=False, tile_align=True)

    assert "tile_crop_offset" in aligned.report
    cropped_width, cropped_height = aligned.report["tile_cropped_size"]
    assert cropped_width <= 129 and cropped_height <= 129
    # The aligned run reports the *original* source size, and its cropped source
    # is a whole number of cells.
    assert aligned.report["source_size"] == [129, 129]
    cells = cropped_width / aligned.grid.pitch[0]
    assert cells == pytest.approx(round(cells), abs=0.5 / aligned.grid.pitch[0] + 1e-9)
    assert aligned.logical.size[0] <= plain.logical.size[0]
