# SPDX-License-Identifier: MIT
"""Generated prompt and operator override resolution."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sprite_studio.spec.layout import prompt_rel

from studio.core.prompt import PromptAssembler, PromptResult
from studio.backend.preset_service import load_preset


def generated_prompt(run_dir: Path, request: dict, state: str) -> str:
    path = run_dir / prompt_rel(request, state)
    if not path.is_file():
        raise FileNotFoundError(f"generated prompt not found: {path}")
    return path.read_text(encoding="utf-8")


def override_path(run_dir: Path, state: str) -> Path:
    return run_dir / "studio" / "prompts" / f"{state}.override.txt"


def effective_prompt(run_dir: Path, request: dict, state: str) -> tuple[str, str]:
    override = override_path(run_dir, state)
    if override.is_file():
        return override.read_text(encoding="utf-8"), "override"
    return generated_prompt(run_dir, request, state), "generated"


def assemble_for_run(run_dir: Path, request: dict[str, Any], state: str, *, profile: str | None = None,
                     background_policy: str | None = None) -> PromptResult:
    direction, pose = state.split("_", 1) if "_" in state else ("", state)
    metadata = json_load(run_dir / "studio" / "studio.json")
    config = metadata.get("config") or {}
    preset = load_preset(str(config.get("preset", "sword")))
    identity = str(preset.get("identity_prompt") or preset.get("character_description") or config.get("character_id", ""))
    base_name = (request.get("character") or {}).get("base_image")
    base = run_dir / base_name if base_name else None
    return PromptAssembler().assemble(
        str(config.get("character_id", (request.get("character") or {}).get("id", "character"))),
        direction,
        pose,
        profile or str(config.get("generation_profile", "refine_first")),
        background_policy=background_policy or str(config.get("background_policy", "auto")),
        identity=identity,
        base_image=base if base and base.is_file() else None,
        action_text=str((request.get("states", {}).get(state) or {}).get("action") or "") or None,
    )


def write_assembled_prompt(run_dir: Path, request: dict[str, Any], state: str, *, profile: str,
                           background_policy: str) -> PromptResult:
    result = assemble_for_run(run_dir, request, state, profile=profile, background_policy=background_policy)
    prompt_path = run_dir / prompt_rel(request, state)
    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path.write_text(result.final_prompt.rstrip() + "\n", encoding="utf-8")
    manifest_path = run_dir / "studio" / "prompts" / f"{state}.manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json_dump(result.to_dict()), encoding="utf-8")
    return result


def save_override(run_dir: Path, state: str, prompt: str) -> Path:
    prompt = prompt.strip()
    if not prompt:
        raise ValueError("prompt override cannot be empty")
    path = override_path(run_dir, state)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(prompt.rstrip() + "\n", encoding="utf-8")
    return path


def reset_override(run_dir: Path, state: str) -> None:
    override_path(run_dir, state).unlink(missing_ok=True)


def json_load(path: Path) -> dict[str, Any]:
    import json
    return json.loads(path.read_text(encoding="utf-8"))


def json_dump(value: dict[str, Any]) -> str:
    import json
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"
