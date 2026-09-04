# SPDX-License-Identifier: Apache-2.0
"""Generation strategy resolution and motion-plan artifacts.

Strategy is deliberately separate from provider execution.  The planner can
explain an AUTO decision and persist a reviewable plan before any image call is
made; a failed row-quality gate can therefore be promoted to a sequential
plan without silently re-running a different pipeline.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from sprite_studio.spec.runio import atomic_write_text

Strategy = Literal["AUTO", "ROW_FAST", "KEYPOSE_SEQUENTIAL"]
STRATEGIES: tuple[Strategy, ...] = ("AUTO", "ROW_FAST", "KEYPOSE_SEQUENTIAL")
_CONFIG_PATH = Path(__file__).resolve().parents[1] / "data" / "config" / "generation_strategy.json"


def _load_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else default
    except (OSError, json.JSONDecodeError):
        return default


def policy() -> dict[str, Any]:
    return _load_json(_CONFIG_PATH, {
        "version": 1,
        "default": "AUTO",
        "states": {},
        "max_row_fast_frames": 4,
        "fallback_on_row_quality_fail": "KEYPOSE_SEQUENTIAL",
    })


def _state_kind(state: str) -> str:
    return state.rsplit("_", 1)[-1].lower()


def _overrides_path(run_dir: Path) -> Path:
    return run_dir / "studio" / "generation-strategy.json"


def _overrides(run_dir: Path) -> dict[str, str]:
    payload = _load_json(_overrides_path(run_dir), {})
    return {str(key): str(value) for key, value in (payload.get("states") or {}).items() if value in STRATEGIES}


def _validate(strategy: str) -> Strategy:
    if strategy not in STRATEGIES:
        raise ValueError(f"strategy must be one of {', '.join(STRATEGIES)}")
    return strategy  # type: ignore[return-value]


def resolve(run_dir: Path, request: dict[str, Any], state: str, requested: str | None = None) -> dict[str, Any]:
    spec = request.get("states", {}).get(state)
    if not isinstance(spec, dict):
        raise ValueError(f"unknown state: {state!r}")
    selected = _validate(requested) if requested else None
    config = policy()
    override = _overrides(run_dir).get(state)
    configured = override or (config.get("states") or {}).get(_state_kind(state)) or config.get("default", "AUTO")
    requested_strategy = selected or (_validate(override) if override else "AUTO")
    frames = int(spec.get("frames", 1))
    max_row_fast = int(config.get("max_row_fast_frames", 4))
    if requested_strategy == "AUTO":
        configured_strategy = _validate(str(configured))
        resolved = configured_strategy if configured_strategy != "AUTO" else ("ROW_FAST" if frames <= max_row_fast and _state_kind(state) not in {"attack", "walk", "run"} else "KEYPOSE_SEQUENTIAL")
        reason = f"AUTO selected {resolved} for {_state_kind(state)} ({frames} frames; row limit {max_row_fast})."
    else:
        resolved = requested_strategy
        reason = f"Explicit {requested_strategy} selection."
    return {
        "requested": requested_strategy,
        "resolved": resolved,
        "reason": reason,
        "policy": config,
        "frames": frames,
    }


def _phase_template(kind: str, loop: bool) -> list[tuple[str, str, float]]:
    if kind in {"attack", "strike", "hit"}:
        return [("ready", "key", 1.0), ("windup", "key", 1.0), ("accel", "between", 1.0), ("impact", "key", 1.2), ("follow", "between", 1.0), ("recovery", "key", 1.0)]
    if kind in {"walk", "run", "move", "locomotion"}:
        return [("contact", "key", 1.0), ("down", "between", 1.0), ("passing", "key", 1.0), ("up", "between", 1.0)] if loop else [("start", "key", 1.0), ("contact", "key", 1.0), ("passing", "between", 1.0), ("end", "key", 1.0)]
    return [("settle", "key", 1.0), ("lift", "between", 1.0), ("peak", "key", 1.0), ("settle", "between", 1.0)]


def motion_plan(run_dir: Path, request: dict[str, Any], state: str, requested: str | None = None) -> dict[str, Any]:
    resolution = resolve(run_dir, request, state, requested)
    spec = request["states"][state]
    frame_count = resolution["frames"]
    template = _phase_template(_state_kind(state), bool(spec.get("loop", False)))
    if frame_count <= len(template):
        selected = template[:frame_count]
    else:
        selected = []
        for index in range(frame_count):
            if index < len(template):
                selected.append(template[index])
            else:
                selected.append((f"between_{index:02d}", "between", 1.0))
    phases = [
        {"index": index, "id": phase_id, "role": role, "weight": weight}
        for index, (phase_id, role, weight) in enumerate(selected)
    ]
    return {
        "kind": "sprite-studio-motion-plan",
        "version": 1,
        "animation": state,
        "loop": bool(spec.get("loop", False)),
        "frames": frame_count,
        "fps": int(spec.get("fps", 8)),
        "strategy": resolution["resolved"],
        "requested_strategy": resolution["requested"],
        "reason": resolution["reason"],
        "phases": phases,
        "key_pose_indices": [item["index"] for item in phases if item["role"] == "key"],
        "fallback_on_row_quality_fail": resolution["policy"].get("fallback_on_row_quality_fail"),
    }


def save_motion_plan(run_dir: Path, plan: dict[str, Any]) -> Path:
    path = run_dir / "studio" / "motion-plans" / f"{plan['animation']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps(plan, ensure_ascii=False, indent=2) + "\n")
    return path


def load_motion_plan(run_dir: Path, state: str) -> dict[str, Any] | None:
    path = run_dir / "studio" / "motion-plans" / f"{state}.json"
    payload = _load_json(path, {})
    return payload or None


def set_override(run_dir: Path, state: str, strategy: str) -> dict[str, str]:
    value = _validate(strategy)
    payload = _load_json(_overrides_path(run_dir), {"version": 1, "states": {}})
    states = {str(key): str(item) for key, item in (payload.get("states") or {}).items()}
    states[state] = value
    payload.update({"version": 1, "states": states})
    _overrides_path(run_dir).parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(_overrides_path(run_dir), json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return states
