from __future__ import annotations

import pytest

import sprite_studio.gen as gen


def test_codex_image_generation_requires_explicit_capability_opt_in(monkeypatch) -> None:
    monkeypatch.delenv(gen.CODEX_IMAGE_GEN_ENV, raising=False)

    available, message = gen.codex_image_generation_available()

    assert not available
    assert "does not expose image generation" in message
    with pytest.raises(SystemExit, match="SPRITE_STUDIO_CODEX_IMAGE_GEN"):
        gen._make_provider("codex", keep_session=False)


def test_codex_image_generation_can_be_enabled_for_verified_cli(monkeypatch) -> None:
    monkeypatch.setenv(gen.CODEX_IMAGE_GEN_ENV, "1")

    available, message = gen.codex_image_generation_available()

    assert available
    assert "explicitly enabled" in message
