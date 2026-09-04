# SPDX-License-Identifier: Apache-2.0
"""Provider-backed key-pose and bidirectional inbetween generation.

This service keeps sequential work in a separate manifest until the operator
approves key poses.  The existing row extractor/refiner is therefore never
fed a half-approved sequence by accident.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sprite_studio.gen import generate_image
from sprite_studio.spec.layout import guide_rel
from sprite_studio.spec.runio import atomic_write_text

from .prompt_service import effective_prompt
from .spritegen_bridge import request_for
from .strategy_service import motion_plan, save_motion_plan


def _sequence_dir(run_dir: Path, state: str) -> Path:
    return run_dir / "studio" / "sequential" / state


def _manifest_path(run_dir: Path, state: str) -> Path:
    return _sequence_dir(run_dir, state) / "manifest.json"


def _load_manifest(run_dir: Path, state: str) -> dict[str, Any]:
    path = _manifest_path(run_dir, state)
    if not path.is_file():
        return {"kind": "sprite-studio-sequential", "state": state, "status": "planned", "key_poses": [], "inbetweens": [], "accepted_key_poses": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"sequential manifest is invalid for {state}: {exc}") from exc


def load_manifest(run_dir: Path, state: str) -> dict[str, Any]:
    return _load_manifest(run_dir, state)


def _save_manifest(run_dir: Path, state: str, payload: dict[str, Any]) -> None:
    path = _manifest_path(run_dir, state)
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def _provider(run_dir: Path, provider: str | None) -> str:
    if provider:
        return provider
    metadata = json.loads((run_dir / "studio" / "studio.json").read_text(encoding="utf-8"))
    return str(metadata["config"]["provider"])


def _identity_refs(run_dir: Path, request: dict[str, Any], state: str) -> list[Path]:
    refs: list[Path] = []
    if (request.get("directions") or {}).get("set"):
        from sprite_studio.curate.anchor import anchor_state, base_source, identity_ref, state_direction
        direction = state_direction(request, state)
        if direction is not None and state == anchor_state(request, direction):
            try:
                refs.append(base_source(run_dir))
            except SystemExit:
                pass
        else:
            refs.append(identity_ref(run_dir, state, request=request, quiet=True))
    else:
        base = (request.get("character") or {}).get("base_image")
        if base and (run_dir / base).is_file():
            refs.append(run_dir / base)
    guide = run_dir / guide_rel(request, state)
    if guide.is_file():
        refs.append(guide)
    return refs


def _ensure_plan(run_dir: Path, request: dict[str, Any], state: str) -> dict[str, Any]:
    plan = motion_plan(run_dir, request, state, "KEYPOSE_SEQUENTIAL")
    save_motion_plan(run_dir, plan)
    return plan


def generate_key_poses(run_dir: Path, state: str, *, provider: str | None = None) -> dict[str, Any]:
    request = request_for(run_dir)
    plan = _ensure_plan(run_dir, request, state)
    directory = _sequence_dir(run_dir, state)
    directory.mkdir(parents=True, exist_ok=True)
    base_prompt, _source = effective_prompt(run_dir, request, state)
    refs = _identity_refs(run_dir, request, state)
    generated: list[dict[str, Any]] = []
    for phase in plan["phases"]:
        if phase["role"] != "key":
            continue
        index = int(phase["index"])
        output = directory / f"key-{index:02d}.png"
        prompt = (
            f"{base_prompt.strip()}\n\n[KEY POSE REQUEST]\n"
            f"Render only the accepted key pose for animation phase '{phase['id']}' at frame {index + 1}. "
            "Return one character image, not a sprite strip and not multiple panels. "
            "Keep the attached identity anchor authoritative."
        )
        result = generate_image(
            _provider(run_dir, provider), prompt, output, refs=refs,
            aspect_ratio="1:1", workdir=directory / "work" / f"key-{index:02d}",
        )
        generated.append({"index": index, "phase": phase["id"], "role": "key", "path": str(result.out), "provider": result.provider, "model": result.model})
    manifest = _load_manifest(run_dir, state) | {
        "kind": "sprite-studio-sequential",
        "state": state,
        "status": "pending_key_pose_approval",
        "motion_plan": plan,
        "key_poses": generated,
        "inbetweens": [],
        "accepted_key_poses": [],
    }
    _save_manifest(run_dir, state, manifest)
    return manifest


def approve_key_poses(run_dir: Path, state: str, indices: list[int]) -> dict[str, Any]:
    manifest = _load_manifest(run_dir, state)
    available = {int(item["index"]) for item in manifest.get("key_poses", []) if Path(item.get("path", "")).is_file()}
    requested = sorted(set(int(index) for index in indices))
    missing = [index for index in requested if index not in available]
    if missing:
        raise ValueError(f"cannot approve missing key poses: {missing}")
    if len(requested) < 2:
        raise ValueError("approve at least two key poses before generating inbetweens")
    manifest["accepted_key_poses"] = requested
    manifest["status"] = "key_poses_approved"
    _save_manifest(run_dir, state, manifest)
    return manifest


def generate_inbetweens(run_dir: Path, state: str, *, provider: str | None = None) -> dict[str, Any]:
    request = request_for(run_dir)
    manifest = _load_manifest(run_dir, state)
    accepted = sorted(set(int(index) for index in manifest.get("accepted_key_poses", [])))
    if len(accepted) < 2:
        raise ValueError("approve at least two key poses before generating inbetweens")
    plan = manifest.get("motion_plan") or _ensure_plan(run_dir, request, state)
    key_by_index = {int(item["index"]): Path(item["path"]) for item in manifest.get("key_poses", [])}
    directory = _sequence_dir(run_dir, state)
    base_prompt, _source = effective_prompt(run_dir, request, state)
    generated: list[dict[str, Any]] = []
    for phase in plan["phases"]:
        if phase["role"] != "between":
            continue
        index = int(phase["index"])
        previous = max((item for item in accepted if item < index), default=None)
        following = min((item for item in accepted if item > index), default=None)
        if previous is None or following is None:
            continue
        previous_path = key_by_index.get(previous)
        following_path = key_by_index.get(following)
        if not previous_path or not following_path or not previous_path.is_file() or not following_path.is_file():
            raise ValueError(f"accepted key pose references are missing around frame {index}")
        refs = _identity_refs(run_dir, request, state) + [previous_path, following_path]
        prompt = (
            f"{base_prompt.strip()}\n\n[INBETWEEN REQUEST]\n"
            f"Create one inbetween image for phase '{phase['id']}' at frame {index + 1}. "
            f"Interpolate motion between accepted key poses F{previous} and F{following}. "
            "Preserve identity, scale, facing, palette, and silhouette; return one image only."
        )
        output = directory / f"between-{index:02d}.png"
        result = generate_image(
            _provider(run_dir, provider), prompt, output, refs=refs,
            aspect_ratio="1:1", workdir=directory / "work" / f"between-{index:02d}",
        )
        generated.append({"index": index, "phase": phase["id"], "role": "between", "path": str(result.out), "between": [previous, following], "provider": result.provider, "model": result.model})
    manifest["inbetweens"] = generated
    manifest["status"] = "sequential_frames_generated"
    _save_manifest(run_dir, state, manifest)
    return manifest
