# SPDX-License-Identifier: Apache-2.0
"""Shared Core contracts: colour metric, config, palette, grid seam."""

from __future__ import annotations

import numpy as np
import pytest
from PIL import Image, ImageDraw

from sprite_studio.frames.extract import axis_edge_histograms
from studio.shared.color import nearest_index, oklab_to_rgb, rgb_delta_e, rgb_to_oklab
from studio.shared.config import apply_overrides, load_refine_settings, settings_from_dict
from studio.shared.grid import axis_edge_profiles, cell_weights, grid_edges, scan_axis, weight_curve
from studio.shared.modes import resolve_asset_type, resolve_mode
from studio.shared.palette import apply_palette, build_palette, palette_distance_report


def test_oklab_matches_reference_values() -> None:
    # Ottosson's published sRGB->Oklab values; if this drifts, every distance
    # threshold tuned against it silently changes meaning.
    lab = rgb_to_oklab(np.array([[255, 0, 0], [255, 255, 255], [0, 0, 0]], dtype=np.uint8))
    assert lab[0] == pytest.approx([0.6280, 0.2249, 0.1258], abs=1e-3)
    assert lab[1] == pytest.approx([1.0, 0.0, 0.0], abs=1e-3)
    assert lab[2] == pytest.approx([0.0, 0.0, 0.0], abs=1e-3)


def test_oklab_round_trips_byte_exact() -> None:
    colors = np.array([[255, 0, 0], [18, 52, 86], [200, 150, 50], [0, 255, 0]], dtype=np.uint8)
    assert np.array_equal(oklab_to_rgb(rgb_to_oklab(colors)), colors)


def test_oklab_distance_orders_perceptually() -> None:
    navy = np.array([20, 30, 90], dtype=np.uint8)
    near_navy = np.array([24, 34, 96], dtype=np.uint8)
    orange = np.array([230, 140, 30], dtype=np.uint8)
    assert rgb_delta_e(navy, near_navy) < rgb_delta_e(navy, orange)


def test_nearest_index_picks_closest_palette_entry() -> None:
    palette = rgb_to_oklab(np.array([[0, 0, 0], [255, 255, 255]], dtype=np.uint8))
    query = rgb_to_oklab(np.array([[20, 20, 20], [240, 240, 240]], dtype=np.uint8))
    assert list(nearest_index(query, palette)) == [0, 1]


def test_numpy_edge_profile_matches_the_engine_definition() -> None:
    """Studio's fast profile must equal the engine's, pixel for pixel.

    Studio picks the grid the engine then snaps to. Two different edge
    definitions would mean two different grids for the same image.
    """
    image = Image.new("RGBA", (70, 56), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    for block_y in range(8):
        for block_x in range(10):
            draw.rectangle(
                (block_x * 7, block_y * 7, block_x * 7 + 6, block_y * 7 + 6),
                fill=(30 + block_x * 20, 40 + block_y * 15, 200 - block_x * 10, 255),
            )
    columns, rows = axis_edge_profiles(image)
    reference_columns, reference_rows, _, _ = axis_edge_histograms(image)
    assert list(columns) == reference_columns
    assert list(rows) == reference_rows


def test_weight_curve_never_reaches_zero_on_a_small_cell() -> None:
    """The whole point of §5.4: a 3px cell must keep usable weight everywhere."""
    settings = load_refine_settings("sprite")
    weights = cell_weights(0, 3, settings.weighting.anchors)
    assert weights.min() > 0.0
    assert weights[1] == pytest.approx(1.0)
    assert weights[0] == weights[2]


def test_weight_curve_follows_the_declared_anchors() -> None:
    anchors = ((0.0, 1.0), (0.5, 0.7), (0.8, 0.3), (1.0, 0.1))
    assert weight_curve(np.array([0.0, 0.5, 0.8, 1.0]), anchors) == pytest.approx([1.0, 0.7, 0.3, 0.1])
    # Monotone decreasing: a pixel further from the centre never counts for more.
    sampled = weight_curve(np.linspace(0.0, 1.0, 40), anchors)
    assert np.all(np.diff(sampled) <= 1e-12)


def test_grid_edges_span_the_image_with_a_fractional_pitch() -> None:
    edges = grid_edges(30, 6.1, 0.3)
    assert edges[0] == 0 and edges[-1] == 30
    assert all(later > earlier for earlier, later in zip(edges, edges[1:]))


def test_scan_axis_breaks_score_ties_toward_an_integer_pitch() -> None:
    """A tie taken arbitrarily accumulates drift and invents trailing cells."""
    rng = np.random.default_rng(7)
    truth = Image.fromarray(
        np.dstack([rng.integers(30, 220, (32, 32), dtype=np.uint8) for _ in range(3)]
                  + [np.full((32, 32), 255, np.uint8)]), "RGBA")
    scene = truth.resize((256, 256), Image.Resampling.NEAREST)
    columns, _ = axis_edge_profiles(scene)
    fit = scan_axis([int(v) for v in columns], {8.0}, min_pitch=2.0, max_pitch=64.0, half_span=0.75, step=0.02)
    assert fit.pitch == pytest.approx(8.0, abs=1e-9)


def test_palette_build_is_deterministic_and_stays_in_gamut() -> None:
    image = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle((2, 2, 14, 29), fill=(200, 40, 40, 255))
    draw.rectangle((16, 2, 29, 29), fill=(40, 60, 200, 255))
    first = build_palette([image], 2)
    assert first == build_palette([image], 2)
    source_colors = {(200, 40, 40, 255), (40, 60, 200, 255)}
    assert set(first) <= source_colors


def test_apply_palette_maps_everything_onto_the_palette() -> None:
    image = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
    ImageDraw.Draw(image).rectangle((1, 1, 14, 14), fill=(123, 77, 200, 255))
    palette = ((10, 10, 10, 255), (250, 250, 250, 255))
    remapped = np.asarray(apply_palette(image, palette))
    opaque = remapped[remapped[:, :, 3] >= 128][:, :3]
    assert {tuple(int(v) for v in color) for color in np.unique(opaque, axis=0)} <= {(10, 10, 10), (250, 250, 250)}


def test_palette_distance_report_flags_a_collapsed_pair() -> None:
    report = palette_distance_report(((10, 10, 10, 255), (11, 11, 11, 255), (240, 10, 10, 255)))
    assert report["min_delta_e"] < 0.02


def test_refine_config_rejects_unknown_sections_and_overrides() -> None:
    with pytest.raises(ValueError, match="unknown sections"):
        settings_from_dict("sprite", {"nonsense": {}})
    with pytest.raises(ValueError, match="unknown refine override"):
        apply_overrides(load_refine_settings("sprite"), {"not_a_setting": 1})
    with pytest.raises(ValueError, match="unknown keys"):
        settings_from_dict("sprite", {"phase": {"tolerance": 0.2, "bogus": True}})


def test_refine_config_rejects_a_malformed_weighting_curve() -> None:
    with pytest.raises(ValueError, match="sorted by increasing radius"):
        settings_from_dict("static", {"weighting": {"anchors": [[0.0, 1.0], [0.8, 0.3], [0.5, 0.7], [1.0, 0.1]]}})
    with pytest.raises(ValueError, match="span radius"):
        settings_from_dict("static", {"weighting": {"anchors": [[0.1, 1.0], [1.0, 0.1]]}})


def test_flat_project_overrides_reach_the_right_section() -> None:
    settings = apply_overrides(
        load_refine_settings("static"),
        {"dither_mode": "serpentine", "seam_check": True, "shared_lattice_scope": "character"},
    )
    assert settings.dither.mode == "serpentine"
    assert settings.seam.check is True
    assert settings.lattice.scope == "character"


def test_static_config_grid_section_loads_as_lattice() -> None:
    """Static spells it "grid", Sprite spells it "lattice"; one field holds both."""
    settings = settings_from_dict("static", {"grid": {"max_pitch": 64}})
    assert settings.lattice.max_pitch == 64


def test_mode_registry_refuses_undeclared_modes() -> None:
    assert resolve_mode("sprite").id == "sprite"
    assert resolve_asset_type("static", "tile_set") == "TILE_SET"
    with pytest.raises(ValueError):
        resolve_mode(None)
    with pytest.raises(ValueError):
        resolve_mode("fx")
    with pytest.raises(ValueError, match="not valid for"):
        resolve_asset_type("static", "character")
