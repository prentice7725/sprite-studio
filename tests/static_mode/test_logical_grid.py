# SPDX-License-Identifier: Apache-2.0
"""Sanity checks for the 128-logical-pixel transport validator."""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw

from studio.static_mode.pixelize.logical_grid import validate_and_unzoom


def _logical_sprite() -> Image.Image:
    image = Image.new("RGBA", (64, 128), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle((20, 0, 43, 127), fill=(38, 62, 110, 255))
    draw.rectangle((24, 18, 39, 35), fill=(220, 174, 126, 255))
    draw.rectangle((18, 8, 45, 16), fill=(32, 24, 42, 255))
    draw.rectangle((14, 90, 19, 112), fill=(214, 180, 40, 255))
    return image


def _tall_canvas_with_128px_subject() -> Image.Image:
    image = Image.new("RGBA", (80, 160), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle((24, 16, 55, 143), fill=(38, 62, 110, 255))
    return image


def test_genuine_nearest_neighbor_8x_preview_passes_and_restores_logical_pixels():
    logical = _logical_sprite()
    transport = logical.resize((logical.width * 8, logical.height * 8), Image.Resampling.NEAREST)

    result = validate_and_unzoom(transport)

    assert result.pass_
    assert (result.inferred_scale_x, result.inferred_scale_y) == (8, 8)
    assert result.logical_image is not None
    assert np.array_equal(np.asarray(result.logical_image), np.asarray(logical))


def test_lanczos_preview_does_not_pass_as_an_exact_logical_grid():
    logical = _logical_sprite()
    transport = logical.resize((logical.width * 8, logical.height * 8), Image.Resampling.LANCZOS)

    result = validate_and_unzoom(transport)

    assert not result.pass_
    assert result.logical_image is None
    assert any(warning["code"] == "FAIL_LOGICAL_GRID" for warning in result.warnings)


def test_exact_subject_height_does_not_resize_a_taller_logical_canvas():
    logical = _tall_canvas_with_128px_subject()
    transport = logical.resize((logical.width * 8, logical.height * 8), Image.Resampling.NEAREST)

    result = validate_and_unzoom(transport)

    assert result.pass_
    assert result.logical_image is not None
    assert result.logical_image.size == logical.size
    alpha = np.asarray(result.logical_image)[:, :, 3]
    ys = np.where(alpha >= 128)[0]
    assert int(ys.max() - ys.min() + 1) == 128


def test_subject_height_tolerance_is_not_accepted():
    logical = Image.new("RGBA", (80, 160), (0, 0, 0, 0))
    ImageDraw.Draw(logical).rectangle((24, 16, 55, 142), fill=(38, 62, 110, 255))
    transport = logical.resize((logical.width * 8, logical.height * 8), Image.Resampling.NEAREST)

    result = validate_and_unzoom(transport)

    assert not result.pass_
    assert any(warning["code"] == "logical-subject-height-not-exact" for warning in result.warnings)


def test_general_high_resolution_illustration_fails_even_when_dimensions_have_an_integer_scale():
    height = width = 1024
    array = np.zeros((height, width, 4), dtype=np.uint8)
    yy, xx = np.mgrid[:height, :width]
    array[:, :, 0] = (xx * 17 + yy * 3) % 256
    array[:, :, 1] = (yy * 19 + xx * 5) % 256
    array[:, :, 2] = (xx * 7 + yy * 23) % 256
    array[:, :, 3] = 255

    result = validate_and_unzoom(Image.fromarray(array, mode="RGBA"))

    assert not result.pass_
    assert result.logical_image is None
    assert any(warning["code"] == "FAIL_LOGICAL_GRID" for warning in result.warnings)
