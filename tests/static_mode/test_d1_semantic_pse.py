from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from PIL import Image, ImageDraw

from studio.backend import provider_service
from studio.static_mode.pixelize.d1_d2 import SemanticPseOptions, d1_semantic_pse_file


def test_d1_semantic_redraw_projects_to_validated_logical_master(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source.png"
    Image.new("RGBA", (64, 64), (20, 20, 20, 255)).save(source)

    def fake_generate(provider: str, prompt: str, out: Path, *, refs=None, **kwargs):
        out.parent.mkdir(parents=True, exist_ok=True)
        image = Image.new("RGBA", (256, 256), (255, 0, 255, 255))
        ImageDraw.Draw(image).rectangle((64, 32, 191, 223), fill=(48, 88, 160, 255))
        image.save(out)
        return SimpleNamespace(to_dict=lambda: {"provider": provider, "model": "fake", "prompt": prompt})

    monkeypatch.setattr(provider_service, "generate_image", fake_generate)
    result = d1_semantic_pse_file(source, tmp_path / "d1", provider="grok", options=SemanticPseOptions())

    assert result.report["status"] == "PASS_LOGICAL_MASTER"
    assert result.accepted_path is not None
    assert Image.open(result.accepted_path).height == 128
