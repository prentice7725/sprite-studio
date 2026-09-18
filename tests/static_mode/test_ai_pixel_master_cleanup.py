from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
from PIL import Image, ImageDraw

from studio.backend import provider_service
from studio.static_mode.pixelize.ai_cleanup import AiPixelMasterCleanupOptions, ai_pixel_master_cleanup
from studio.static_mode.pixelize.c2 import C2Options, c2_pixel_master_file


def test_ai_cleanup_removes_chroma_preserves_clusters_and_normalizes_height() -> None:
    image = Image.new("RGBA", (256, 256), (0, 255, 0, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle((64, 32, 191, 223), fill=(54, 93, 174, 255))
    draw.rectangle((86, 64, 104, 86), fill=(240, 220, 180, 255))
    image.putpixel((230, 20), (255, 255, 255, 255))

    result = ai_pixel_master_cleanup(image, AiPixelMasterCleanupOptions(target_size=128))

    assert result.image.height == 128
    assert result.image.width == 85
    assert result.report["background"]["mode"] == "chroma:green"
    assert result.report["isolated_noise"]["removed_pixels"] == 1
    alpha = np.asarray(result.image)[:, :, 3]
    assert set(np.unique(alpha).tolist()) <= {0, 255}
    assert result.image.getpixel((0, 0))[:3] != (0, 255, 0)


def test_c2_requires_the_128px_profile() -> None:
    try:
        C2Options(target_size=96)
    except ValueError as exc:
        assert "target_size=128" in str(exc)
    else:  # pragma: no cover - assertion branch
        raise AssertionError("C2 accepted a non-128 target")


def test_c2_keeps_intermediate_raw_post_and_provider_provenance(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source.png"
    Image.new("RGBA", (64, 64), (20, 20, 20, 255)).save(source)
    calls: list[tuple[Path, list[Path]]] = []

    def fake_generate(provider: str, prompt: str, out: Path, *, refs=None, **kwargs):
        references = list(refs or [])
        calls.append((out, references))
        out.parent.mkdir(parents=True, exist_ok=True)
        image = Image.new("RGBA", (256, 256), (255, 0, 255, 255))
        ImageDraw.Draw(image).rectangle((64, 32, 191, 223), fill=(50, 110, 210, 255))
        image.save(out)
        return SimpleNamespace(to_dict=lambda: {"provider": provider, "prompt": prompt, "refs": [str(p) for p in references]})

    monkeypatch.setattr(provider_service, "generate_image", fake_generate)
    result = c2_pixel_master_file(source, tmp_path / "pixelized", provider="grok")

    assert len(calls) == 2
    assert calls[0][1] == [source]
    assert calls[1][1] == [source, result.intermediate_path]
    assert result.intermediate_path.is_file()
    assert result.raw_path.is_file()
    assert result.post_path.is_file()
    assert result.report_path.is_file()
    assert result.report["strategy"] == "reference_pixel_master_128"
    assert result.report["accepted"] == "post"
    assert Image.open(result.post_path).size == (85, 128)
