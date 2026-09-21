# SPDX-License-Identifier: Apache-2.0

from pathlib import Path
from types import SimpleNamespace

from PIL import Image, ImageDraw

from studio.backend import provider_service
from studio.static_mode.pixelize.c1 import C1Options, c1_pixel_master_file


def _valid_transport() -> Image.Image:
    logical = Image.new("RGBA", (64, 128), (0, 0, 0, 0))
    ImageDraw.Draw(logical).rectangle((18, 0, 45, 127), fill=(50, 110, 210, 255))
    return logical.resize((512, 1024), Image.Resampling.NEAREST)


def test_c1_grid_pass_creates_logical_post_without_geometry_resize(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source.png"
    Image.new("RGBA", (64, 64), (20, 20, 20, 255)).save(source)

    def fake_generate(provider: str, prompt: str, out: Path, *, refs=None, **kwargs):
        out.parent.mkdir(parents=True, exist_ok=True)
        _valid_transport().save(out)
        return SimpleNamespace(to_dict=lambda: {"provider": provider, "refs": [str(p) for p in refs or []]})

    monkeypatch.setattr(provider_service, "generate_image", fake_generate)
    result = c1_pixel_master_file(source, tmp_path / "pixelized", provider="grok")

    assert result.accepted_path == result.post_path
    assert result.report["status"] == "PASS"
    assert result.report["logical_validation"]["pass"] is True
    assert result.report["cleanup"]["geometry"]["resize"] is False
    assert Image.open(result.accepted_path).size == (64, 128)


def test_c1_grid_fail_never_emits_logical_or_accepted_output(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source.png"
    Image.new("RGBA", (64, 64), (20, 20, 20, 255)).save(source)

    def fake_generate(provider: str, prompt: str, out: Path, *, refs=None, **kwargs):
        out.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGBA", (256, 256), (255, 0, 255, 255)).save(out)
        return SimpleNamespace(to_dict=lambda: {"provider": provider})

    monkeypatch.setattr(provider_service, "generate_image", fake_generate)
    result = c1_pixel_master_file(source, tmp_path / "pixelized", provider="grok", options=C1Options())

    assert result.accepted_path is None
    assert result.logical_path is None
    assert result.report["status"] == "FAIL_LOGICAL_GRID"
    assert not (tmp_path / "pixelized" / "logical" / "source.png").exists()
