# SPDX-License-Identifier: Apache-2.0
"""Generated prompt and operator override resolution.

SPRITE_STUDIO_PROMPT_PIPELINE_REGRESSION_FIX_DIRECTIVE §3: the upstream row
contract (`sprite_studio.gen.prepare.row_prompt`, written once by
`prepare.run()`) is the production authority for frame count, slot layout,
anchor lock, and per-state motion language. `PromptAssembler` must EXTEND that
contract with studio-specific notes (style profile, identity override,
target-aware negative) — never replace it. `write_assembled_prompt` therefore
always recomputes the base row prompt straight from `prepare.row_prompt`
(deterministic given request/state) rather than reading it back off a prompt
file that a previous call may already have extended, so repeated calls stay
idempotent instead of stacking extensions on top of each other.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sprite_studio.gen import prepare
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


def base_row_prompt(request: dict[str, Any], state: str) -> str:
    """The upstream sprite-gen row contract for `state` — frame count, slot
    layout, anchor lock, transparency rules, all state-specific motion
    language. Deterministic from `request`/`state` alone (§3), so callers can
    recompute it any time instead of reading a possibly-already-extended file
    back off disk."""
    entry = request["states"][state]
    return prepare.row_prompt(request, state, entry)


def assemble_for_run(run_dir: Path, request: dict[str, Any], state: str, *, profile: str | None = None,
                     background_policy: str | None = None) -> PromptResult:
    direction, pose = state.split("_", 1) if "_" in state else ("", state)
    metadata = json_load(run_dir / "studio" / "studio.json")
    config = metadata.get("config") or {}
    preset = load_preset(str(config.get("preset", "sword")))
    identity = str(preset.get("identity_prompt") or preset.get("character_description") or config.get("character_id", ""))
    base_name = (request.get("character") or {}).get("base_image")
    base = run_dir / base_name if base_name else None
    # §4: frame count is read from the request SSOT (states[state].frames), never hardcoded.
    frames = int(request["states"][state]["frames"])
    return PromptAssembler().assemble(
        str(config.get("character_id", (request.get("character") or {}).get("id", "character"))),
        direction,
        pose,
        profile or str(config.get("generation_profile", "refine_first")),
        frames=frames,
        background_policy=background_policy or str(config.get("background_policy", "auto")),
        identity=identity,
        base_image=base if base and base.is_file() else None,
        action_text=str((request.get("states", {}).get(state) or {}).get("action") or "") or None,
    )


def merge_row_and_studio_prompt(base_prompt: str, studio: PromptResult) -> str:
    """§3.1 block ownership: the upstream row contract stays the authoritative
    [PRODUCTION CONTRACT] block; Studio's contribution is appended as clearly
    labeled extension blocks that refine it (identity override, style profile,
    target-aware negative) instead of overwriting it."""
    sections = [
        "[PRODUCTION CONTRACT]",
        base_prompt.strip(),
        "",
        "[STUDIO PRODUCTION EXTENSIONS]",
        "The following notes refine, but do not replace, the production contract above.",
        "",
        "[IDENTITY LOCK]",
        studio.blocks["identity"],
        "",
        "[MOTION CONTINUITY NOTE]",
        studio.blocks["direction_action"],
        "",
        "[STYLE]",
        studio.blocks["style_profile"],
        studio.blocks["refiner_safe_suffix"],
        "",
        "[NEGATIVE]",
        studio.blocks["negative"],
    ]
    return "\n".join(sections).strip() + "\n"


def write_assembled_prompt(run_dir: Path, request: dict[str, Any], state: str, *, profile: str,
                           background_policy: str) -> PromptResult:
    studio_result = assemble_for_run(run_dir, request, state, profile=profile, background_policy=background_policy)
    base_prompt = base_row_prompt(request, state)
    final_prompt = merge_row_and_studio_prompt(base_prompt, studio_result)
    # `PromptResult.final_prompt` / manifest carry the merged text so downstream
    # readers (manifest debugging, generation) see exactly what gets written.
    result = studio_result.__class__(
        studio_result.character_id, studio_result.direction, studio_result.state,
        studio_result.generation_profile, studio_result.target_kind, studio_result.frame_count,
        studio_result.background, {"production_contract": base_prompt, **studio_result.blocks},
        final_prompt, studio_result.issues,
    )
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
