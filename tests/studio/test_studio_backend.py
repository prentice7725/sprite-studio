# SPDX-License-Identifier: MIT
"""Phase 1 Studio service contracts."""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw

from studio.backend import run_manager, spritegen_bridge
from studio.backend.prompt_service import effective_prompt, reset_override, save_override
from studio.backend.schemas import StudioRunConfig
from studio.core.prompt import PromptAssembler, PromptValidator


def _base(path: Path) -> None:
    image = Image.new("RGB", (64, 64), (255, 0, 255))
    ImageDraw.Draw(image).rectangle((22, 16, 42, 55), fill=(80, 80, 80))
    image.save(path)


def test_create_run_builds_engine_request_and_studio_metadata(tmp_path: Path) -> None:
    base = tmp_path / "base.png"
    _base(base)
    config = StudioRunConfig(
        run_id="sword_a01",
        character_id="sword",
        provider="grok",
        base_image=base,
        directions=("down", "side", "up"),
        mirrors={"left": "side"},
        states={"idle": {"frames": 4, "fps": 4, "loop": True, "action": "idle"}},
        preset="sword",
    )

    info = run_manager.create_run(config, root=tmp_path / "runs")

    assert info.path == tmp_path / "runs" / "sword_a01"
    request = json.loads((info.path / "sprite-request.json").read_text(encoding="utf-8"))
    assert list(request["states"]) == ["down_idle", "side_idle", "up_idle"]
    assert request["directions"]["mirror"] == {"left": "side"}
    assert (info.path / "studio" / "studio.json").is_file()
    metadata = json.loads((info.path / "studio" / "studio.json").read_text(encoding="utf-8"))
    assert metadata["config"]["generation_profile"] == "refine_first"
    prompt_manifest = json.loads((info.path / "studio" / "prompts" / "side_idle.manifest.json").read_text(encoding="utf-8"))
    assert prompt_manifest["generation_profile"] == "refine_first"
    assert set(prompt_manifest["blocks"]) == {"identity", "direction_action", "style_profile", "refiner_safe_suffix", "negative"}
    assert run_manager.get_run_status("sword_a01", root=tmp_path / "runs")["side_idle"] == "not-generated"


def test_prompt_override_is_explicit_and_reversible(tmp_path: Path) -> None:
    base = tmp_path / "base.png"
    _base(base)
    config = StudioRunConfig(
        run_id="sword_a02", character_id="sword", provider="grok", base_image=base,
        directions=("side",), mirrors={}, states={"idle": {"frames": 4}}, preset="sword",
    )
    info = run_manager.create_run(config, root=tmp_path / "runs")
    request = spritegen_bridge.request_for(info.path)
    generated, source = effective_prompt(info.path, request, "side_idle")
    assert source == "generated"
    save_override(info.path, "side_idle", "custom prompt")
    assert effective_prompt(info.path, request, "side_idle") == ("custom prompt\n", "override")
    reset_override(info.path, "side_idle")
    assert effective_prompt(info.path, request, "side_idle") == (generated, "generated")


def test_prompt_profiles_are_assembled_and_validated() -> None:
    result = PromptAssembler().assemble(
        "sword", "side", "attack", "direct_pixel", background_policy="green",
        identity="plain steel swordsman",
    )

    assert result.blocks["style_profile"].startswith("DIRECT_PIXEL")
    assert "#00FF00" in result.blocks["refiner_safe_suffix"]
    assert not [issue for issue in result.issues if issue.severity == "error"]
    assert not PromptValidator().validate(result.final_prompt)


def test_attack_prompt_locks_weapon_handedness_and_uses_state_action() -> None:
    result = PromptAssembler().assemble(
        "sword", "side", "attack", "refine_first", background_policy="green",
        identity="swordsman", action_text="four-frame sword strike: windup, slash, recovery",
    )

    assert "four-frame sword strike" in result.blocks["direction_action"]
    assert "same physical weapon hand" in result.blocks["direction_action"]
    assert "HANDEDNESS_CONSTRAINT_MISSING" not in {issue.code for issue in result.issues}
