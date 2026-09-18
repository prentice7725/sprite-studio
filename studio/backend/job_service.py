# SPDX-License-Identifier: Apache-2.0
"""Persistent single-operation jobs for the Studio pipeline.

This module is the seam between HTTP/WebSocket transport and the existing
Studio services.  A job owns only orchestration state; the existing backend
modules remain the source of truth for generation, extraction, repair, QA, and
export.  Job files are deliberately separate from ``batch-queue.json`` so the
legacy Batch contract remains stable while individual operations gain the same
background execution model.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from sprite_studio.spec.runio import atomic_write_text

from . import export_service, qa_service, repair_service, sequential_service, spritegen_bridge, strategy_service


_TERMINAL = {"succeeded", "failed", "cancelled", "interrupted"}
_ACTIVE: dict[str, threading.Thread] = {}
_CANCEL: dict[str, threading.Event] = {}
_RUN_ACTIVE: dict[str, str] = {}
_LOCK = threading.RLock()

_OPERATIONS = {
    "generate", "normalize", "extract", "refine",
    "repair_analyze", "repair_safe", "repair_decide", "repair_undo",
    "repair_adopt", "repair_unadopt", "animation_qa",
    "export_compose", "export_runtime",
    "sequential_key_poses", "sequential_inbetweens", "sequential_promote",
    "quick_make",
}
_STATE_OPERATIONS = {
    operation for operation in _OPERATIONS
    if operation not in {"export_compose", "export_runtime"}
}


class JobCancelled(Exception):
    """Internal cooperative cancellation signal."""


class JobOperationFailure(Exception):
    """A failed operation with structured, user-actionable result data."""

    def __init__(self, message: str, result: dict[str, Any]) -> None:
        super().__init__(message)
        self.result = result


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _jobs_dir(run_dir: Path) -> Path:
    return Path(run_dir) / "studio" / "jobs"


def _job_path(run_dir: Path, job_id: str) -> Path:
    if not job_id or Path(job_id).name != job_id or job_id in {".", ".."}:
        raise ValueError("invalid job id")
    return _jobs_dir(run_dir) / f"{job_id}.json"


def _save(run_dir: Path, payload: dict[str, Any]) -> None:
    path = _job_path(run_dir, str(payload["job_id"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def _elapsed(payload: dict[str, Any]) -> int | None:
    started = payload.get("started_at")
    if not started:
        return None
    try:
        start = datetime.fromisoformat(str(started))
        return max(0, int((datetime.now(timezone.utc) - start).total_seconds()))
    except (TypeError, ValueError):
        return None


def _update(run_dir: Path, payload: dict[str, Any], **changes: Any) -> None:
    payload.update(changes)
    payload["updated_at"] = _now()
    payload["elapsed_seconds"] = _elapsed(payload)
    _save(run_dir, payload)


def _relative(run_dir: Path, path: Path | str) -> str:
    return Path(path).resolve().relative_to(Path(run_dir).resolve()).as_posix()


def _check_cancel(job_id: str) -> None:
    with _LOCK:
        event = _CANCEL.get(job_id)
    if event is not None and event.is_set():
        raise JobCancelled("job cancellation requested")


def _generate(run_dir: Path, state: str) -> dict[str, Any]:
    report = spritegen_bridge.generate_state(run_dir, state)
    return {
        "provider": report["provider"],
        "prompt": report["prompt"],
        "raw_asset_path": _relative(run_dir, report["out"]),
        "raw_bytes": report["raw_bytes"],
        "elapsed_seconds": report["elapsed_seconds"],
        "model": report.get("model"),
        "refs_paths": [_relative(run_dir, ref) for ref in report.get("refs", [])],
        "transparent": report["transparent"],
        "prompt_source": report["prompt_source"],
    }


def _normalize(run_dir: Path, state: str, options: dict[str, Any]) -> dict[str, Any]:
    # The requested strategy is retained in the job record for replay/audit;
    # normalize itself consumes the run's persisted strategy decision.
    try:
        report = spritegen_bridge.normalize_state(run_dir, state)
    except spritegen_bridge.NormalizeQualityFailed as exc:
        fallback = strategy_service.fallback_after_row_quality_failure(
            run_dir,
            spritegen_bridge.request_for(run_dir),
            state,
            options.get("strategy"),
        )
        failure = {"result": "fail", "error": str(exc), "report": exc.report, "fallback": fallback}
        if fallback and fallback.get("motion_plan_path"):
            failure["motion_plan_asset_path"] = _relative(run_dir, fallback["motion_plan_path"])
        raise JobOperationFailure(str(exc), failure) from exc
    return {
        "result": report["result"],
        "output_asset_path": _relative(run_dir, report["output"]),
        "output_size": list(report["output_size"]),
        "expected_subjects": report["expected_subjects"],
        "valid_subjects": report["valid_subjects"],
        "report": report,
        "strategy": options.get("strategy"),
    }


def _refine(run_dir: Path, state: str) -> dict[str, Any]:
    result = spritegen_bridge.refine_frames(run_dir, state)
    outputs = list(result.output_files)
    return {
        "refined_preview_asset_path": _relative(run_dir, outputs[0]) if outputs else None,
        "output_files_paths": [_relative(run_dir, path) for path in outputs],
        "report": result.report,
    }


def _quick_make(run_dir: Path, state: str, options: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    """Run the existing sprite pipeline as one user-facing Quick job."""
    requested_states = [str(item) for item in (options.get("states") or [state])]
    stage_order = ("generate", "normalize", "extract", "refine", "animation_qa")
    total = max(1, len(requested_states) * len(stage_order) + 2)
    completed = 0
    state_results: list[dict[str, Any]] = []
    for current_state in requested_states:
        state_result: dict[str, Any] = {"state": current_state}
        for stage in stage_order:
            _check_cancel(str(payload["job_id"]))
            progress = min(96.0, (completed / total) * 100.0)
            _update(run_dir, payload, current_stage=f"{stage}:{current_state}", progress_percent=progress)
            if stage == "generate":
                state_result[stage] = _generate(run_dir, current_state)
            elif stage == "normalize":
                state_result[stage] = _normalize(run_dir, current_state, options)
            elif stage == "extract":
                code = spritegen_bridge.extract_frames(run_dir, current_state)
                state_result[stage] = {"exit_code": code}
                if code != 0:
                    raise RuntimeError(f"extract failed for {current_state} with exit code {code}")
            elif stage == "refine":
                state_result[stage] = _refine(run_dir, current_state)
            else:
                state_result[stage] = {"qa": spritegen_bridge.animation_qa(run_dir, current_state).to_dict()}
            completed += 1
        state_results.append(state_result)

    _check_cancel(str(payload["job_id"]))
    _update(run_dir, payload, current_stage="preparing_preview", progress_percent=97.0)
    from sprite_studio.qa import preview as qa_preview
    qa_preview.run(run_dir=run_dir)
    code = export_service.compose(run_dir)
    if code != 0:
        raise RuntimeError(f"compose failed with exit code {code}")
    target_state = str(options.get("target_state") or state)
    result: dict[str, Any] = {
        "states": state_results,
        "sprite_sheet_asset_path": "sprite-sheet-alpha.png",
        "manifest_asset_path": "manifest.json",
    }
    preview_path = run_dir / "qa" / f"{target_state}.gif"
    if preview_path.is_file():
        result["preview_gif_asset_path"] = _relative(run_dir, preview_path)
    return result

def _execute_operation(run_dir: Path, operation: str, state: str | None, options: dict[str, Any], payload: dict[str, Any] | None = None) -> dict[str, Any]:
    if operation in _STATE_OPERATIONS and not state:
        raise ValueError(f"operation {operation!r} requires a state")
    if operation == "quick_make":
        return _quick_make(run_dir, str(state), options, payload or {"job_id": "unknown"})
    if operation == "generate":
        return _generate(run_dir, str(state))
    if operation == "normalize":
        return _normalize(run_dir, str(state), options)
    if operation == "extract":
        code = spritegen_bridge.extract_frames(run_dir, str(state))
        return {"exit_code": code, "summary": qa_service.summary(run_dir, str(state)) or ("extract complete" if code == 0 else f"extract exit code {code}")}
    if operation == "refine":
        return _refine(run_dir, str(state))
    if operation == "repair_analyze":
        return {"analysis": repair_service.analyze_state(run_dir, str(state))}
    if operation == "repair_safe":
        repair_service.analyze_state(run_dir, str(state))
        return {"repair": repair_service.repair_state(run_dir, str(state))}
    if operation == "repair_decide":
        ids = {str(item) for item in options.get("candidate_ids", [])}
        accepted = bool(options.get("accept", False))
        return {"decision": repair_service.decide_candidates(run_dir, str(state), ids, accept=accepted)}
    if operation == "repair_undo":
        repair_service.clear_repairs(run_dir, str(state))
        return {"source": "canonical"}
    if operation == "repair_adopt":
        return {"adopt": repair_service.adopt_repaired(run_dir, str(state))}
    if operation == "repair_unadopt":
        return {"unadopt": repair_service.unadopt_repaired(run_dir, str(state))}
    if operation == "animation_qa":
        return {"qa": spritegen_bridge.animation_qa(run_dir, str(state)).to_dict()}
    if operation == "export_compose":
        code = export_service.compose(run_dir)
        if code != 0:
            raise RuntimeError(f"compose failed with exit code {code}")
        return {
            "sprite_sheet_asset_path": "sprite-sheet-alpha.png",
            "manifest_asset_path": "manifest.json",
        }
    if operation == "export_runtime":
        result = export_service.build_runtime(run_dir)
        return {
            "atlas_asset_path": _relative(run_dir, result["atlas"]),
            "manifest_asset_path": _relative(run_dir, result["manifest"]),
            "size": list(result["size"]),
        }
    if operation == "sequential_key_poses":
        manifest = sequential_service.generate_key_poses(run_dir, str(state))
        return {"status": manifest.get("status", "key_poses_generated")}
    if operation == "sequential_inbetweens":
        manifest = sequential_service.generate_inbetweens(run_dir, str(state))
        return {"status": manifest.get("status", "inbetweens_generated")}
    if operation == "sequential_promote":
        manifest = sequential_service.promote_to_shared_frames(run_dir, str(state))
        return {"status": manifest.get("status", "promoted"), "promoted": True}
    raise ValueError(f"unknown job operation: {operation!r}")


def _worker(run_dir: Path, payload: dict[str, Any]) -> None:
    job_id = str(payload["job_id"])
    try:
        _check_cancel(job_id)
        _update(run_dir, payload, status="running", current_stage=payload["operation"], progress_percent=5.0, started_at=payload["started_at"])
        result = _execute_operation(run_dir, str(payload["operation"]), payload.get("state"), dict(payload.get("options") or {}), payload)
        _check_cancel(job_id)
        _update(run_dir, payload, status="succeeded", current_stage="complete", progress_percent=100.0, result=result, finished_at=_now(), error=None)
    except JobCancelled as exc:
        _update(run_dir, payload, status="cancelled", current_stage="cancelled", error=str(exc), finished_at=_now())
    except JobOperationFailure as exc:
        _update(run_dir, payload, status="failed", current_stage="failed", result=exc.result, error=str(exc), finished_at=_now())
    except BaseException as exc:  # engine uses SystemExit as a fail-loud signal
        _update(
            run_dir,
            payload,
            status="failed",
            current_stage="failed",
            error=f"{type(exc).__name__}: {exc}",
            finished_at=_now(),
        )
    finally:
        with _LOCK:
            _ACTIVE.pop(job_id, None)
            _CANCEL.pop(job_id, None)
            if _RUN_ACTIVE.get(str(Path(run_dir).resolve())) == job_id:
                _RUN_ACTIVE.pop(str(Path(run_dir).resolve()), None)


def _mark_stale(run_dir: Path, payload: dict[str, Any]) -> dict[str, Any]:
    job_id = str(payload.get("job_id"))
    with _LOCK:
        thread = _ACTIVE.get(job_id)
    if payload.get("status") in {"running", "cancel_requested"} and (thread is None or not thread.is_alive()):
        status = "cancelled" if payload.get("cancel_requested") else "interrupted"
        _update(run_dir, payload, status=status, current_stage=status, error=payload.get("error") or "job worker terminated before completion", finished_at=_now())
    return payload


def load_job(run_dir: Path, job_id: str) -> dict[str, Any] | None:
    path = _job_path(run_dir, job_id)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "job_id": job_id,
            "operation": "generate",
            "state": None,
            "status": "interrupted",
            "current_stage": "failed",
            "progress_percent": 0.0,
            "cancel_requested": False,
            "attempt": 1,
            "parent_job_id": None,
            "result": None,
            "error": f"job state is unreadable: {exc}",
            "created_at": _now(),
            "started_at": None,
            "updated_at": _now(),
            "finished_at": _now(),
            "elapsed_seconds": None,
        }
    if not isinstance(payload, dict):
        return None
    return _mark_stale(run_dir, payload)


def list_jobs(run_dir: Path) -> list[dict[str, Any]]:
    jobs = []
    for path in _jobs_dir(run_dir).glob("*.json"):
        job = load_job(run_dir, path.stem)
        if job:
            jobs.append(job)
    return sorted(jobs, key=lambda item: str(item.get("created_at", "")), reverse=True)


def start_job(
    run_dir: Path,
    operation: str,
    *,
    state: str | None = None,
    options: dict[str, Any] | None = None,
    parent_job_id: str | None = None,
    attempt: int = 1,
) -> str:
    if operation not in _OPERATIONS:
        raise ValueError(f"unknown job operation: {operation!r}")
    if operation in _STATE_OPERATIONS and not state:
        raise ValueError(f"operation {operation!r} requires a state")
    run_key = str(Path(run_dir).resolve())
    with _LOCK:
        existing = _RUN_ACTIVE.get(run_key)
        if existing:
            thread = _ACTIVE.get(existing)
            if thread and thread.is_alive():
                raise RuntimeError(f"job {existing} is already running for this run")
            _RUN_ACTIVE.pop(run_key, None)

        job_id = uuid4().hex[:12]
        now = _now()
        payload: dict[str, Any] = {
            "kind": "sprite-studio-job",
            "job_id": job_id,
            "operation": operation,
            "state": state,
            "status": "running",
            "current_stage": "queued",
            "progress_percent": 0.0,
            "cancel_requested": False,
            "attempt": attempt,
            "parent_job_id": parent_job_id,
            "options": dict(options or {}),
            "result": None,
            "error": None,
            "created_at": now,
            "started_at": now,
            "updated_at": now,
            "finished_at": None,
            "elapsed_seconds": 0,
        }
        _save(run_dir, payload)
        event = threading.Event()
        thread = threading.Thread(target=_worker, args=(Path(run_dir), payload), daemon=True, name=f"sprite-studio-job-{job_id}")
        _ACTIVE[job_id] = thread
        _CANCEL[job_id] = event
        _RUN_ACTIVE[run_key] = job_id
        thread.start()
        return job_id


def cancel_job(run_dir: Path, job_id: str) -> dict[str, Any]:
    payload = load_job(run_dir, job_id)
    if payload is None:
        raise FileNotFoundError(f"job not found: {job_id}")
    if payload.get("status") in _TERMINAL:
        return payload
    with _LOCK:
        event = _CANCEL.get(job_id)
        if event is not None:
            event.set()
    _update(run_dir, payload, status="cancel_requested", cancel_requested=True, current_stage="cancel_requested")
    return payload


def retry_job(run_dir: Path, job_id: str) -> str:
    payload = load_job(run_dir, job_id)
    if payload is None:
        raise FileNotFoundError(f"job not found: {job_id}")
    if payload.get("status") not in {"failed", "cancelled", "interrupted"}:
        raise ValueError(f"only failed, cancelled, or interrupted jobs can be retried (status: {payload.get('status')})")
    return start_job(
        run_dir,
        str(payload["operation"]),
        state=payload.get("state"),
        options=dict(payload.get("options") or {}),
        parent_job_id=str(payload["job_id"]),
        attempt=int(payload.get("attempt", 1)) + 1,
    )


def active_job(run_dir: Path) -> str | None:
    with _LOCK:
        job_id = _RUN_ACTIVE.get(str(Path(run_dir).resolve()))
        thread = _ACTIVE.get(job_id) if job_id else None
        return job_id if thread and thread.is_alive() else None
