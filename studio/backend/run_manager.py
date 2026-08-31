# SPDX-License-Identifier: Apache-2.0
"""Studio run lifecycle; the existing prepare module owns run scaffolding."""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any

from PIL import Image

from sprite_studio.gen import prepare
from sprite_studio.spec.layout import frames_dir_rel, raw_rel

from studio.shared.modes import SPRITE, resolve_mode

from .preset_service import load_preset, preset_states
from .prompt_service import write_assembled_prompt
from studio.core.prompt.background_policy import resolve_background
from .schemas import RunInfo, StudioRunConfig


RUNS_ROOT_ENV = "SPRITE_STUDIO_RUNS_ROOT"
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


def runs_root(root: Path | None = None) -> Path:
    value = root or Path(os.environ.get(RUNS_ROOT_ENV, "runs"))
    return value.expanduser().resolve()


def _validate_config(config: StudioRunConfig) -> None:
    if resolve_mode(config.mode).id != SPRITE:
        raise ValueError("run_manager owns Sprite Mode runs; static projects go through static_service")
    if not _SAFE_ID.fullmatch(config.run_id):
        raise ValueError("run_id must contain only letters, numbers, '_' or '-' and start alphanumeric")
    if not config.character_id.strip():
        raise ValueError("character_id cannot be empty")
    if config.provider not in {"grok", "codex"}:
        raise ValueError("provider must be grok or codex")
    if not config.directions:
        raise ValueError("at least one direction is required")
    if not config.states:
        raise ValueError("at least one state is required")
    if config.cell_size <= 0 or config.runtime_size <= 0:
        raise ValueError("cell sizes must be positive")


def _request_input(config: StudioRunConfig) -> dict[str, Any]:
    states: dict[str, dict[str, Any]] = {}
    for direction in config.directions:
        for pose, entry in config.states.items():
            states[f"{direction}_{pose}"] = dict(entry)
    return {
        "states": states,
        "directions": {"set": list(config.directions), "mirror": dict(config.mirrors)},
        "style": "pixel-art game sprite, clean readable silhouette, consistent character model",
    }


def create_run(config: StudioRunConfig, *, root: Path | None = None) -> RunInfo:
    _validate_config(config)
    root = runs_root(root)
    run_dir = root / config.run_id
    if run_dir.exists() and any(run_dir.iterdir()):
        raise FileExistsError(f"run already exists and is not empty: {run_dir}")
    root.mkdir(parents=True, exist_ok=True)
    request_input = _request_input(config)
    background = resolve_background(config.background_policy, config.base_image)
    prepare_key = background.get("hex") or "auto"
    prepare.run(
        out_dir=run_dir,
        character_id=config.character_id,
        base_image=config.base_image,
        description=config.description,
        style="pixel-art game sprite, clean readable silhouette, consistent character model",
        subject="character",
        cell_size=config.cell_size,
        cell_width=None,
        cell_height=None,
        safe_margin=None,
        chroma_key=prepare_key,
        fit_resample=None,
        fit_align_x=None,
        fit_align_y=None,
        fit_ground_frames=None,
        fit_pixel_unfake=None,
        fit_logical_height=None,
        fit_palette_size=None,
        fit_detail_bias=None,
        fit_outline=None,
        fit_pitch_hint=None,
        motion_phase_guides=False,
        directions=None,
        mirror=None,
        request=None,
        request_json=json.dumps(request_input),
        force=False,
    )
    request_path = run_dir / "sprite-request.json"
    request = json.loads(request_path.read_text(encoding="utf-8"))
    metadata = {
        "version": 1,
        "kind": "sprite-studio-run",
        "mode": config.mode,
        "config": asdict(config) | {"base_image": str(config.base_image) if config.base_image else None},
        "run_dir": str(run_dir),
        "prompt_profiles": {"generation": config.generation_profile, "negative": "default"},
    }
    studio_dir = run_dir / "studio"
    studio_dir.mkdir(parents=True, exist_ok=True)
    (studio_dir / "studio.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for state in request["states"]:
        write_assembled_prompt(
            run_dir,
            request,
            state,
            profile=config.generation_profile,
            background_policy=config.background_policy,
        )
    return load_run(config.run_id, root=root)


def _load_metadata(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "studio" / "studio.json"
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def load_run(run_id: str, *, root: Path | None = None) -> RunInfo:
    if not _SAFE_ID.fullmatch(run_id):
        raise ValueError(f"invalid run id: {run_id!r}")
    run_dir = runs_root(root) / run_id
    request_path = run_dir / "sprite-request.json"
    if not request_path.is_file():
        raise FileNotFoundError(f"sprite request not found: {request_path}")
    request = json.loads(request_path.read_text(encoding="utf-8"))
    metadata = _load_metadata(run_dir)
    cfg = metadata.get("config") or {}
    cell = request.get("cell") or {}
    directions = tuple((request.get("directions") or {}).get("set") or cfg.get("directions") or [])
    return RunInfo(
        run_id=run_id,
        path=run_dir,
        character_id=str((request.get("character") or {}).get("id", cfg.get("character_id", run_id))),
        provider=str(cfg.get("provider", "grok")),
        preset=str(cfg.get("preset", "sword")),
        directions=directions,
        states=tuple(request.get("states") or {}),
        cell_size=int(cell.get("width", cfg.get("cell_size", 256))),
        runtime_size=int(cfg.get("runtime_size", 48)),
        generation_profile=str(cfg.get("generation_profile", "refine_first")),
        background_policy=str(cfg.get("background_policy", "auto")),
        # Runs created before the mode split carry no mode field. They are sprite
        # runs by construction (nothing else existed), so defaulting is a fact
        # about history here, not a guess.
        mode=resolve_mode(cfg.get("mode") or metadata.get("mode") or SPRITE).id,
        refine=dict(cfg.get("refine") or {}),
        locks=dict(cfg.get("locks") or {}),
    )


def list_runs(*, root: Path | None = None) -> list[RunInfo]:
    root = runs_root(root)
    if not root.is_dir():
        return []
    result: list[RunInfo] = []
    for path in sorted(root.iterdir()):
        if path.is_dir() and _SAFE_ID.fullmatch(path.name) and (path / "sprite-request.json").is_file():
            try:
                result.append(load_run(path.name, root=root))
            except (OSError, ValueError, json.JSONDecodeError):
                continue
    return result


def delete_run(run_id: str, *, root: Path | None = None) -> None:
    """Delete one exact run directory; callers must request this explicitly."""
    import shutil

    run_dir = runs_root(root) / run_id
    if not _SAFE_ID.fullmatch(run_id) or run_dir.parent != runs_root(root):
        raise ValueError("refusing to delete an invalid run id")
    if run_dir.is_dir():
        shutil.rmtree(run_dir)


def get_run_status(run_id: str, *, root: Path | None = None) -> dict[str, str]:
    from .repair_service import repaired_files as current_repaired_files

    info = load_run(run_id, root=root)
    request = json.loads((info.path / "sprite-request.json").read_text(encoding="utf-8"))
    manifest_path = info.path / "frames" / "frames-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
    extracted = {row.get("state") for row in manifest.get("rows", [])}
    statuses: dict[str, str] = {}
    for state in info.states:
        raw = info.path / raw_rel(request, state)
        expected = (int(request["states"][state]["frames"]) * info.cell_size, info.cell_size)
        refined_dir = info.path / frames_dir_rel(request, state) / "refined"
        animation_report = info.path / "studio" / "qa" / f"{state}.animation.json"
        animation_warning = False
        if animation_report.is_file():
            try:
                animation_warning = bool(json.loads(animation_report.read_text(encoding="utf-8")).get("warnings"))
            except json.JSONDecodeError:
                animation_warning = True
        if state in extracted and animation_warning:
            statuses[state] = "warning"
        elif state in extracted and current_repaired_files(info.path, state):
            statuses[state] = "repaired"
        elif state in extracted and refined_dir.is_dir() and any(refined_dir.glob("frame-*.png")):
            statuses[state] = "refined"
        elif state in extracted:
            statuses[state] = "extracted" if not manifest.get("warnings") else "warning"
        elif raw.is_file():
            try:
                with Image.open(raw) as image:
                    statuses[state] = "normalized" if image.size == expected else "raw"
            except OSError:
                statuses[state] = "failed"
        else:
            statuses[state] = "not-generated"
    return statuses
