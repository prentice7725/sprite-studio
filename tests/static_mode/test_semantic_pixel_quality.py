from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw

from studio.static_mode.pixelize.semantic_pixel_quality import evaluate_semantic_source


def test_semantic_quality_accepts_transparent_or_chroma_backed_subject() -> None:
    image = Image.new("RGBA", (256, 256), (255, 0, 255, 255))
    ImageDraw.Draw(image).rectangle((64, 32, 191, 223), fill=(48, 88, 160, 255))

    result = evaluate_semantic_source(image)

    assert result.passed
    assert result.metrics["background"]["mode"] == "chroma:magenta"
    assert result.metrics["subject_bbox"] == [64, 32, 192, 224]


def test_semantic_quality_warns_or_fails_on_color_rich_soft_source() -> None:
    image = Image.new("RGBA", (128, 128), (255, 0, 255, 255))
    array = np.asarray(image).copy()
    yy, xx = np.mgrid[:128, :128]
    array[:, :, 0] = (xx * 3 + yy * 5) % 256
    array[:, :, 1] = (yy * 7 + xx * 2) % 256
    array[:, :, 2] = (xx * 11 + yy * 13) % 256
    array[:8] = (255, 0, 255, 255)
    array[-8:] = (255, 0, 255, 255)
    array[:, :8] = (255, 0, 255, 255)
    array[:, -8:] = (255, 0, 255, 255)

    result = evaluate_semantic_source(Image.fromarray(array, mode="RGBA"))

    assert result.status in {"WARN_PAINTERLY", "FAIL_NOT_ABSTRACTED"}
    assert any(warning["code"] in {"WARN_PAINTERLY", "FAIL_NOT_ABSTRACTED"} for warning in result.warnings)
