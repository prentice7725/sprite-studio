# SPDX-License-Identifier: Apache-2.0
"""Persistent batch queue for the Studio pipeline."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from sprite_studio.spec.runio import atomic_write_text

from . import spritegen_bridge


def _queue_path(run_dir: Path) -> Path:
    return run_dir / "studio" / "batch-queue.json"


def load_queue(run_dir: Path) -> dict[str, Any] | None:
    path = _queue_path(run_dir)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"status": "failed", "error": "batch-queue.json is invalid"}


def _save(run_dir: Path, payload: dict[str, Any]) -> None:
    path = _queue_path(run_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _update(run_dir: Path, payload: dict[str, Any], *, status: str | None = None, **fields: Any) -> None:
    if status:
        payload["status"] = status
    payload.update(fields)
    _save(run_dir, payload)


def _execute(run_dir: Path, payload: dict[str, Any], *, normalize: bool, refine: bool, repair: bool, qa: bool) -> None:
    states = [item["state"] for item in payload["items"]]
    try:
        for item in payload["items"]:
            state = item["state"]
            item["status"] = "generating"
            _update(run_dir, payload)
            item["generate"] = spritegen_bridge.generate_state(run_dir, state)
            if normalize:
                item["status"] = "normalizing"
                _update(run_dir, payload)
                item["normalize"] = spritegen_bridge.normalize_state(run_dir, state)

        item_states = ",".join(states)
        item_status = "extracting"
        for item in payload["items"]:
            item["status"] = item_status
        _update(run_dir, payload)
        code = spritegen_bridge.extract_frames(run_dir, item_states)
        if code != 0:
            raise RuntimeError(f"extract failed with exit code {code}")
        for item in payload["items"]:
            state = item["state"]
            if refine:
                item["status"] = "refining"
                _update(run_dir, payload)
                item["refine"] = spritegen_bridge.refine_frames(run_dir, state).report
            if repair:
                item["status"] = "repairing"
                _update(run_dir, payload)
                item["repair_analysis"] = spritegen_bridge.analyze_repairs(run_dir, state)
                item["repair"] = spritegen_bridge.repair_frames(run_dir, state)
            if qa:
                item["status"] = "qa"
                _update(run_dir, payload)
                item["qa"] = spritegen_bridge.animation_qa(run_dir, state).to_dict()
            item["status"] = "complete"
            _update(run_dir, payload)
        _update(run_dir, payload, status="complete", finished_at=_now())
    except Exception as exc:  # queue state must remain inspectable after provider errors
        payload["error"] = f"{type(exc).__name__}: {exc}"
        _update(run_dir, payload, status="failed", finished_at=_now())


def start_batch(run_dir: Path, states: list[str], *, normalize: bool = True, refine: bool = True,
                repair: bool = False, qa: bool = True) -> str:
    request = spritegen_bridge.request_for(run_dir)
    unique_states = list(dict.fromkeys(state for state in states if state))
    unknown = [state for state in unique_states if state not in request.get("states", {})]
    if unknown:
        raise ValueError(f"unknown batch state(s): {', '.join(unknown)}")
    if not unique_states:
        raise ValueError("select at least one state for the batch")
    current = load_queue(run_dir)
    if current and current.get("status") == "running":
        raise RuntimeError("a batch is already running")
    payload: dict[str, Any] = {
        "kind": "sprite-studio-batch",
        "job_id": uuid4().hex[:12],
        "status": "running",
        "created_at": _now(),
        "options": {"normalize": normalize, "refine": refine, "repair": repair, "qa": qa},
        "items": [{"state": state, "status": "queued"} for state in unique_states],
    }
    _save(run_dir, payload)
    thread = threading.Thread(target=_execute, args=(run_dir, payload), kwargs={"normalize": normalize, "refine": refine, "repair": repair, "qa": qa}, daemon=True, name=f"sprite-studio-batch-{payload['job_id']}")
    thread.start()
    return payload["job_id"]


def status_text(run_dir: Path) -> str:
    payload = load_queue(run_dir)
    if not payload:
        return "배치 큐가 없습니다."
    lines = [f"### Batch `{payload.get('job_id', '?')}` — **{payload.get('status', 'unknown')}**"]
    for item in payload.get("items", []):
        lines.append(f"- `{item.get('state')}`: {item.get('status', 'queued')}")
    if payload.get("error"):
        lines.append(f"\n⚠ {payload['error']}")
    return "\n".join(lines)
