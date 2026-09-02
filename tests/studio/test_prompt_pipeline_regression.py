# SPDX-License-Identifier: Apache-2.0
"""Regression tests for SPRITE_STUDIO_PROMPT_PIPELINE_REGRESSION_FIX_DIRECTIVE.md §13/§14.

The regression: `write_assembled_prompt` used to overwrite the rich upstream
`sprite_studio.gen.prepare.row_prompt()` contract (exact frame count, invisible
slot layout, anchor identity lock) with a short, hardcoded-4-frame,
"single character only" Studio prompt — a self-contradicting spec for any
animation row. These tests pin the fixed contract down so it cannot regress
silently in a future refactor.
"""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw

from studio.backend import run_manager, spritegen_bridge
from studio.backend.prompt_service import base_row_prompt
from studio.backend.schemas import StudioRunConfig
from studio.core.prompt import PromptAssembler, PromptValidator
from studio.core.prompt.profiles import load_negative_profile


def _base(path: Path) -> None:
    image = Image.new("RGB", (64, 64), (255, 0, 255))
    ImageDraw.Draw(image).rectangle((22, 16, 42, 55), fill=(80, 80, 80))
    image.save(path)


# --- A. exact frame count, no hardcoded 4 -----------------------------------

def test_row_prompt_uses_request_frame_count_not_a_hardcoded_four() -> None:
    four = PromptAssembler().assemble("sword", "side", "attack", "direct_pixel", frames=4)
    six = PromptAssembler().assemble("sword", "side", "attack", "direct_pixel", frames=6)

    assert "Exactly 4" in four.blocks["direction_action"]
    assert "Exactly 6" in six.blocks["direction_action"]
    # The old regression literal must never appear again, at any frame count.
    assert "4-frame readable motion when this is an animation row" not in four.final_prompt
    assert "4-frame readable motion when this is an animation row" not in six.final_prompt


# --- B. row prompt must not contain "single character only" -----------------

def test_row_prompt_does_not_contain_single_character_only() -> None:
    result = PromptAssembler().assemble("sword", "side", "attack", "direct_pixel", frames=4)
    assert "single character only" not in result.final_prompt.lower()
    assert not PromptValidator().validate(result.final_prompt, target_kind="animation_row")


# --- C. single prompt keeps the single-subject rule --------------------------

def test_single_prompt_retains_single_character_only() -> None:
    result = PromptAssembler().assemble("sword", "side", "idle", "direct_pixel", frames=1)
    assert "single character only" in result.final_prompt.lower()
    assert result.target_kind == "single"


# --- D. row prompt carries the slot contract ---------------------------------

def test_row_prompt_contains_slot_contract() -> None:
    request = {
        "cell": {"width": 256, "height": 256, "safe_margin_x": 24, "safe_margin_y": 24},
        "chroma_key": {"name": "green", "hex": "#00FF00"},
        "character": {"id": "sword", "description": "test swordsman", "base_image": None},
        "style": "pixel-art game sprite",
        "motion_phase_guides": False,
    }
    entry = {"frames": 4, "action": "windup, strike, recovery"}
    prompt = base_row_prompt({**request, "states": {"attack": entry}}, "attack")
    lowered = prompt.lower()
    assert "equal-width invisible" in lowered
    assert "fill every slot" in lowered
    assert "one complete full-body pose" in lowered
    assert "may cross into the neighboring slot" in lowered


# --- E. target-aware negative -------------------------------------------------

def test_negative_profile_is_target_aware() -> None:
    row_negative = load_negative_profile("animation_row")["text"]
    assert "no unrelated secondary characters" in row_negative

    row_result = PromptAssembler().assemble("sword", "side", "attack", "direct_pixel", frames=4)
    assert "no unrelated secondary characters" in row_result.blocks["negative"]

    single_result = PromptAssembler().assemble("sword", "side", "idle", "direct_pixel", frames=1)
    assert "no extra characters" in single_result.blocks["negative"]


# --- F/H. integration: create_run preserves the upstream contract per state --

def test_create_run_preserves_upstream_row_contract_per_state(tmp_path: Path) -> None:
    base = tmp_path / "base.png"
    _base(base)
    config = StudioRunConfig(
        run_id="sword_regress",
        character_id="sword",
        provider="grok",
        base_image=base,
        directions=("side",),
        mirrors={},
        states={
            "idle": {"frames": 4, "fps": 4, "loop": True, "action": "idle"},
            "attack": {"frames": 6, "fps": 8, "loop": False, "action": "attack"},
        },
        preset="sword",
    )
    info = run_manager.create_run(config, root=tmp_path / "runs")

    idle_manifest = json.loads((info.path / "studio" / "prompts" / "side_idle.manifest.json").read_text(encoding="utf-8"))
    attack_manifest = json.loads((info.path / "studio" / "prompts" / "side_attack.manifest.json").read_text(encoding="utf-8"))

    assert idle_manifest["target_kind"] == "animation_row"
    assert idle_manifest["frame_count"] == 4
    assert "Exactly 4 full-body frames" in idle_manifest["blocks"]["production_contract"]

    assert attack_manifest["frame_count"] == 6
    assert "Exactly 6 full-body frames" in attack_manifest["blocks"]["production_contract"]
    assert "single character only" not in attack_manifest["final_prompt"].lower()
    assert "no unrelated secondary characters" in attack_manifest["final_prompt"].lower()


# --- G. layout guide is attached as an actual provider reference -------------

def test_generate_state_attaches_anchor_and_layout_guide_refs(tmp_path: Path, monkeypatch) -> None:
    base = tmp_path / "base.png"
    _base(base)
    config = StudioRunConfig(
        run_id="sword_refs",
        character_id="sword",
        provider="grok",
        base_image=base,
        directions=("side",),
        mirrors={},
        states={"attack": {"frames": 4, "fps": 8, "loop": False, "action": "attack"}},
        preset="sword",
    )
    info = run_manager.create_run(config, root=tmp_path / "runs")

    captured: dict = {}

    class _FakeResult:
        def to_dict(self) -> dict:
            return {"provider": "grok", "prompt": captured.get("prompt", ""), "out": "", "raw": "",
                     "raw_bytes": 0, "elapsed_seconds": 0.0, "model": None, "session_id": None,
                     "refs": [], "transparent": False, "chroma": None}

    def _fake_generate_one(provider, prompt, raw, *, refs=None, aspect_ratio=None, workdir=None, **kwargs):
        captured["prompt"] = prompt
        captured["refs"] = list(refs or [])
        return _FakeResult()

    monkeypatch.setattr(spritegen_bridge, "generate_one", _fake_generate_one)
    # No curated direction anchor exists in this fixture (nothing extracted
    # yet) — that is a real, separate precondition this test is not about, so
    # it stubs identity_ref to the base reference to isolate what this test
    # actually checks: that the layout guide is attached as refs[1].
    import sprite_studio.curate.anchor as anchor_mod
    monkeypatch.setattr(anchor_mod, "identity_ref", lambda *a, **k: base)

    spritegen_bridge.generate_state(info.path, "side_attack", provider="grok")

    refs = captured["refs"]
    assert len(refs) == 2
    assert refs[0].is_file()  # identity/base reference
    assert refs[1].is_file()
    assert refs[1].name == "attack.png"  # references/layout-guides/side/attack.png
    assert "layout-guides" in str(refs[1]).replace("\\", "/")
