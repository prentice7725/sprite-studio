from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw

from studio.static_mode.pixelize.structure_extractor import (
    StructureExtractorOptions,
    extract_structure,
    validate_logical_master,
)


def _semantic_image() -> Image.Image:
    image = Image.new("RGBA", (256, 256), (255, 0, 255, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle((64, 32, 191, 223), fill=(48, 88, 160, 255))
    draw.rectangle((86, 64, 112, 92), fill=(220, 174, 126, 255))
    draw.rectangle((120, 100, 125, 105), fill=(255, 0, 255, 255))
    return image


def test_pse_creates_aspect_preserving_128_logical_output_and_binary_alpha() -> None:
    result = extract_structure(_semantic_image())

    assert result.passed
    assert result.image is not None
    assert result.image.size == (85, 128)
    assert validate_logical_master(result.image).pass_
    assert set(np.unique(np.asarray(result.image)[:, :, 3]).tolist()) <= {0, 255}


def test_pse_removes_border_chroma_but_preserves_internal_chroma_detail() -> None:
    result = extract_structure(_semantic_image())

    assert result.image is not None
    output = np.asarray(result.image)
    assert result.report["background"]["mode"] == "chroma:magenta"
    # The internal magenta mark is projected into an opaque logical cell; it
    # is not treated as a global color-key deletion.
    assert np.any((output[:, :, 0] >= 170) & (output[:, :, 2] >= 170) & (output[:, :, 3] == 255))


def test_pse_combines_sparse_transparency_with_border_chroma_detection() -> None:
    image = _semantic_image()
    image.putpixel((0, 0), (0, 0, 0, 0))

    result = extract_structure(image)

    assert result.image is not None
    assert result.report["background"]["mode"] == "transparent+chroma:magenta"
    assert validate_logical_master(result.image).pass_
    output = np.asarray(result.image)
    assert result.image.size == (85, 128)
    assert np.any((output[:, :, 0] >= 170) & (output[:, :, 2] >= 170) & (output[:, :, 3] == 255))


def test_pse_does_not_use_geometry_resampling_for_logical_projection() -> None:
    result = extract_structure(_semantic_image(), StructureExtractorOptions(palette_size=24))

    assert result.image is not None
    assert result.report["projection"]["resampling"] is None
    assert result.report["logical_size"] == [85, 128]
