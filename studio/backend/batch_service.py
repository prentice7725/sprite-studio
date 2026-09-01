# SPDX-License-Identifier: Apache-2.0
"""Persistent batch queue and real-time job observability for the Studio pipeline."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from sprite_studio.spec.runio import atomic_write_text

from . import spritegen_bridge


_ACTIVE_THREADS: dict[str, threading.Thread] = {}
_ACTIVE_LOCK = threading.Lock()


def _queue_path(run_dir: Path) -> Path:
    return run_dir / "studio" / "batch-queue.json"


def load_queue(run_dir: Path) -> dict[str, Any] | None:
    path = _queue_path(run_dir)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"status": "failed", "error": "batch-queue.json is invalid"}
    
    # Stale running job detection: if recorded as running but no active thread is alive
    if payload.get("status") == "running":
        job_id = payload.get("job_id")
        with _ACTIVE_LOCK:
            thread = _ACTIVE_THREADS.get(str(job_id))
            if thread is None or not thread.is_alive():
                if not payload.get("error"):
                    payload["error"] = "Worker thread or host process terminated before batch completion"
                payload["status"] = "interrupted"
                payload["finished_at"] = _now()
                _save(run_dir, payload)
                _ACTIVE_THREADS.pop(str(job_id), None)
    return payload


def is_batch_running(run_dir: Path) -> bool:
    queue = load_queue(run_dir)
    return bool(queue and queue.get("status") == "running")


def _save(run_dir: Path, payload: dict[str, Any]) -> None:
    path = _queue_path(run_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _update(run_dir: Path, payload: dict[str, Any], **kwargs: Any) -> None:
    payload.update(kwargs)
    payload["updated_at"] = _now()
    started = payload.get("started_at")
    if started:
        try:
            start_dt = datetime.fromisoformat(started)
            now_dt = datetime.now(timezone.utc)
            payload["elapsed_seconds"] = max(0, int((now_dt - start_dt).total_seconds()))
        except (ValueError, TypeError):
            pass
    _save(run_dir, payload)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _execute(run_dir: Path, payload: dict[str, Any], *, normalize: bool, refine: bool, repair: bool, qa: bool) -> None:
    request = spritegen_bridge.request_for(run_dir)
    states = [item["state"] for item in payload["items"]]
    stages_per_item = 1 + (1 if normalize else 0) + 1 + (1 if refine else 0) + (1 if repair else 0) + (1 if qa else 0)
    total_units = len(states) * stages_per_item
    completed_units = 0
    completed_items = 0

    def progress():
        return min(100.0, round(100.0 * completed_units / max(1, total_units), 1))

    try:
        # Determine anchor ordering if directional
        is_directional = bool((request.get("directions") or {}).get("set"))
        anchor_items = []
        action_items = []
        if is_directional:
            from sprite_studio.curate.anchor import anchor_state, state_direction
            for item in payload["items"]:
                st = item["state"]
                d = state_direction(request, st)
                if d is not None and st == anchor_state(request, d):
                    anchor_items.append(item)
                else:
                    action_items.append(item)
        
        batches_to_gen = [anchor_items, action_items] if (anchor_items and action_items) else [payload["items"]]

        for batch in batches_to_gen:
            if not batch:
                continue
            # Stage 1: Generate & Normalize this batch
            for item in batch:
                state = item["state"]
                item["status"] = "generating"
                _update(run_dir, payload, current_state=state, current_stage="generating", progress_percent=progress())
                item["generate"] = spritegen_bridge.generate_state(run_dir, state)
                completed_units += 1

                if normalize:
                    item["status"] = "normalizing"
                    _update(run_dir, payload, current_state=state, current_stage="normalizing", progress_percent=progress())
                    item["normalize"] = spritegen_bridge.normalize_state(run_dir, state)
                    completed_units += 1

            # Stage 2: Extract this batch
            batch_states = ",".join(item["state"] for item in batch)
            for item in batch:
                item["status"] = "extracting"
            _update(run_dir, payload, current_state=batch[0]["state"], current_stage="extracting", progress_percent=progress())
            code = spritegen_bridge.extract_frames(run_dir, batch_states)
            if code != 0:
                raise RuntimeError(f"extract failed for [{batch_states}] with exit code {code}")
            completed_units += len(batch)

        # Precompute character lattice once if scope == "character"
        character_lattice = None
        if refine:
            from studio.shared.config import apply_overrides, load_refine_settings
            from studio.shared.modes import SPRITE
            from .refine_service import _studio_metadata, estimate_run_character_lattice
            config = (_studio_metadata(run_dir).get("config") or {})
            overrides = dict(config.get("refine") or {})
            engine_version = str(overrides.get("engine", "v2"))
            if engine_version == "v2":
                settings = apply_overrides(load_refine_settings(SPRITE), {k: v for k, v in overrides.items() if k != "engine"})
                if settings.lattice.scope == "character":
                    character_lattice = estimate_run_character_lattice(run_dir, states=states, settings=settings)

        # Stage 3: Refine, Repair, QA per state
        for item in payload["items"]:
            state = item["state"]
            if refine:
                item["status"] = "refining"
                _update(run_dir, payload, current_state=state, current_stage="refining", progress_percent=progress())
                if character_lattice is not None:
                    item["refine"] = spritegen_bridge.refine_frames(run_dir, state, shared_lattice=character_lattice).report
                else:
                    item["refine"] = spritegen_bridge.refine_frames(run_dir, state).report
                completed_units += 1

            if repair:
                item["status"] = "repairing"
                _update(run_dir, payload, current_state=state, current_stage="repairing", progress_percent=progress())
                item["repair_analysis"] = spritegen_bridge.analyze_repairs(run_dir, state)
                item["repair"] = spritegen_bridge.repair_frames(run_dir, state)
                completed_units += 1

            if qa:
                item["status"] = "qa"
                _update(run_dir, payload, current_state=state, current_stage="qa", progress_percent=progress())
                item["qa"] = spritegen_bridge.animation_qa(run_dir, state).to_dict()
                completed_units += 1

            item["status"] = "complete"
            completed_items += 1
            _update(run_dir, payload, completed_items=completed_items, progress_percent=progress())

        _update(
            run_dir,
            payload,
            status="complete",
            current_stage="complete",
            current_state=None,
            completed_items=len(states),
            progress_percent=100.0,
            finished_at=_now(),
        )
    except Exception as exc:
        current_st = payload.get("current_state")
        current_sg = payload.get("current_stage")
        payload["error"] = f"{type(exc).__name__} at {current_st} (Stage: {current_sg}): {exc}"
        payload["failed_state"] = current_st
        payload["failed_stage"] = current_sg
        _update(run_dir, payload, status="failed", finished_at=_now())
    finally:
        with _ACTIVE_LOCK:
            _ACTIVE_THREADS.pop(str(payload.get("job_id")), None)


def start_batch(
    run_dir: Path,
    states: list[str],
    *,
    normalize: bool = True,
    refine: bool = True,
    repair: bool = False,
    qa: bool = True,
) -> str:
    request = spritegen_bridge.request_for(run_dir)
    unique_states = list(dict.fromkeys(state for state in states if state))
    unknown = [state for state in unique_states if state not in request.get("states", {})]
    if unknown:
        raise ValueError(f"unknown batch state(s): {', '.join(unknown)}")
    if not unique_states:
        raise ValueError("select at least one state for the batch")
    if is_batch_running(run_dir):
        raise RuntimeError("a batch is already running")

    job_id = uuid4().hex[:12]
    now_str = _now()
    payload: dict[str, Any] = {
        "kind": "sprite-studio-batch",
        "job_id": job_id,
        "status": "running",
        "current_state": unique_states[0],
        "current_stage": "queued",
        "completed_items": 0,
        "total_items": len(unique_states),
        "progress_percent": 0.0,
        "started_at": now_str,
        "updated_at": now_str,
        "elapsed_seconds": 0,
        "options": {"normalize": normalize, "refine": refine, "repair": repair, "qa": qa},
        "items": [{"state": state, "status": "queued"} for state in unique_states],
        "error": None,
    }
    _save(run_dir, payload)
    thread = threading.Thread(
        target=_execute,
        args=(run_dir, payload),
        kwargs={"normalize": normalize, "refine": refine, "repair": repair, "qa": qa},
        daemon=True,
        name=f"sprite-studio-batch-{job_id}",
    )
    with _ACTIVE_LOCK:
        _ACTIVE_THREADS[job_id] = thread
    thread.start()
    return job_id


def status_text(run_dir: Path) -> str:
    payload = load_queue(run_dir)
    if not payload:
        return "배치 큐가 없습니다."
    
    status = payload.get("status", "unknown").upper()
    job_id = payload.get("job_id", "?")
    progress = payload.get("progress_percent", 0.0)
    completed = payload.get("completed_items", 0)
    total = payload.get("total_items", len(payload.get("items", [])))
    current_state = payload.get("current_state")
    current_stage = payload.get("current_stage")
    elapsed = payload.get("elapsed_seconds", 0)
    mins, secs = divmod(elapsed, 60)
    time_str = f"{mins:02d}:{secs:02d}"

    lines = [f"### Batch `{job_id}` — **{status}** ({progress:.1f}%)"]
    
    if status == "RUNNING":
        lines.append(f"**진행**: {completed} / {total} states complete | **현재**: `{current_state}` [{str(current_stage).upper()}] | **경과 시간**: {time_str}")
    elif status == "COMPLETE":
        lines.append(f"**완료**: 전체 {total}개 상태 처리 완료 | **총 소요 시간**: {time_str}")
    elif status in {"FAILED", "INTERRUPTED"}:
        lines.append(f"**중단/실패**: {completed} / {total} states | **실패 위치**: `{payload.get('failed_state')}` [{str(payload.get('failed_stage')).upper()}]")

    lines.append("")
    for item in payload.get("items", []):
        st = item.get("status", "queued")
        icon = "✓" if st == "complete" else "⟳" if st in {"generating", "normalizing", "extracting", "refining", "repairing", "qa"} else "⏳"
        lines.append(f"- {icon} `{item.get('state')}`: {st}")
        
    if payload.get("error"):
        lines.append(f"\n> ⚠ **오류**: {payload['error']}")
    return "\n".join(lines)
