# SPDX-License-Identifier: Apache-2.0
"""Source-first Quick Generate orchestration.

Quick Generate is intentionally a thin product workflow over the existing
Studio services. It owns only the short-lived source session and defaults;
image generation, Pixelize M1, sprite extraction, refinement, QA, and export
remain delegated to their existing engines.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

from PIL import Image

from sprite_studio.spec.runio import atomic_save_image, atomic_write_text
from studio.api.uploads import resolve_upload
from studio.backend import job_service, run_manager
from studio.backend.prompt_service import write_assembled_prompt
from studio.backend.schemas import StudioRunConfig
from studio.static_mode.pixelize import PixelizeOptions
from studio.static_mode.pixelize.validation import PixelMasterValidationError


QUICK_ROOT_ENV = "SPRITE_STUDIO_QUICK_ROOT"
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


def sessions_root() -> Path:
    return Path(__import__("os").environ.get(QUICK_ROOT_ENV, str(run_manager.runs_root() / ".quick-sessions"))).expanduser().resolve()


def _session_dir(session_id: str) -> Path:
    if not _SAFE_ID.fullmatch(session_id):
        raise ValueError(f"invalid quick session id: {session_id!r}")
    return sessions_root() / session_id


def _metadata_path(session_id: str) -> Path:
    return _session_dir(session_id) / "quick-session.json"


def _read(session_id: str) -> dict[str, Any]:
    path = _metadata_path(session_id)
    if not path.is_file():
        raise FileNotFoundError(f"quick session not found: {session_id}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"quick session metadata is invalid: {session_id}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"quick session metadata is invalid: {session_id}")
    return payload


def _write(session_id: str, payload: dict[str, Any]) -> None:
    atomic_write_text(_metadata_path(session_id), json.dumps(payload, ensure_ascii=False, indent=2) + "\n")

def _copy_as_png(source: Path, destination: Path) -> None:
    with Image.open(source) as opened:
        atomic_save_image(opened.convert("RGBA"), destination)


def _response_payload(payload: dict[str, Any]) -> dict[str, Any]:
    session_id = str(payload["session_id"])
    root = _session_dir(session_id)
    original = root / "source" / "original.png"
    pixelized = root / str(payload.get("pixelized_source")) if payload.get("pixelized_source") else None
    preview = root / str(payload.get("pixelized_preview")) if payload.get("pixelized_preview") else None
    subject = root / str(payload.get("subject_source")) if payload.get("subject_source") else None
    return {
        "session_id": session_id,
        "run_id": payload.get("run_id"),
        "job_id": payload.get("job_id"),
        "source_kind": payload["source_kind"],
        "source_status": "ready" if original.is_file() else "failed",
        "source_selection": payload.get("source_selection", "original"),
        "original_source": f"/api/quick/sessions/{session_id}/assets/source/original.png",
        "pixelized_source": f"/api/quick/sessions/{session_id}/assets/{payload['pixelized_source']}" if pixelized and pixelized.is_file() else None,
        "pixelized_preview": f"/api/quick/sessions/{session_id}/assets/{payload['pixelized_preview']}" if preview and preview.is_file() else None,
        "subject_source": f"/api/quick/sessions/{session_id}/assets/{payload['subject_source']}" if subject and subject.is_file() else None,
        "prompt": str(payload.get("prompt") or ""),
        "motion": str(payload.get("motion") or "idle"),
        "style": str(payload.get("style") or "pixel-art"),
        "background": str(payload.get("background") or "transparent"),
        "notes": str(payload.get("notes") or ""),
        "provider": str(payload.get("provider") or "grok"),
    }

def load_session(session_id: str) -> dict[str, Any]:
    return _read(session_id)


def create_session(body: Any) -> dict[str, Any]:
    session_id = uuid4().hex[:12]
    root = _session_dir(session_id)
    source_dir = root / "source"
    source_dir.mkdir(parents=True, exist_ok=False)
    payload: dict[str, Any] = {
        "kind": "sprite-studio-quick-session",
        "version": 1,
        "session_id": session_id,
        "source_kind": "upload",
        "source_selection": "original",
        "prompt": "",
        "motion": body.motion,
        "custom_motion": str(body.custom_motion or "").strip(),
        "style": "pixel-art",
        "background": "transparent",
        "notes": "",
        "provider": "grok",
        "run_id": None,
        "job_id": None,
        "subject_source": None,
    }
    _copy_as_png(resolve_upload(body.upload_id), source_dir / "original.png")
    _write(session_id, payload)
    return payload


def pixelize_session(session_id: str, body: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    payload = _read(session_id)
    source = _session_dir(session_id) / "source" / "original.png"
    if not source.is_file():
        raise FileNotFoundError("quick source image is missing")
    # Reuse the M1.1 engine directly; Static Mode's project adapter is not
    # duplicated just to make a source-session façade.
    from studio.static_mode.pixelize import pixelize_file
    target_size = getattr(body, "size", getattr(body, "pixel_size", 128))
    background = getattr(body, "background", None)
    if background is None:
        background = "cleanup" if getattr(body, "background_cleanup", False) else "keep"
    options = PixelizeOptions(
        target_size=target_size,
        palette_size=None if body.palette == "auto" else int(body.palette),
        dither=body.dither,
        background=background,
        outline=body.outline,
        subject_mode=body.subject_mode,
        subject_bbox=body.subject_bbox,
        detail=body.detail,
        alpha_threshold=body.alpha_threshold,
    )
    try:
        output = pixelize_file(source, _session_dir(session_id) / "pixelized", options, stem="source")
    except PixelMasterValidationError as exc:
        payload["pixelize_strategy"] = "preserve"
        payload["pixelize_accepted"] = "validation_failed"
        payload["pixelize_validation"] = exc.validation.to_dict()
        _write(session_id, payload)
        raise
    payload["pixelized_source"] = "pixelized/source.png"
    payload["pixelized_preview"] = "pixelized/source.preview-4x.png"
    payload["subject_source"] = "pixelized/source.subject.png"
    payload["pixelize_strategy"] = "preserve"
    payload["pixelize_accepted"] = "logical_master"
    payload["pixelize_options"] = body.model_dump()
    _write(session_id, payload)
    detail = {
        "session_id": session_id,
        "strategy": "preserve",
        "accepted": "logical_master",
        "output_source": f"/api/quick/sessions/{session_id}/assets/pixelized/source.png",
        "preview_source": f"/api/quick/sessions/{session_id}/assets/pixelized/source.preview-4x.png",
        "subject_source": f"/api/quick/sessions/{session_id}/assets/pixelized/source.subject.png",
        "subject_bbox": list(output.subject_bbox),
        "subject_candidates": list(output.subject_candidates),
        "logical_size": list(output.logical_size),
        "palette_size": len(output.palette),
        "palette": [list(entry) for entry in output.palette],
        "warnings": list(output.warnings),
        "report": output.report,
    }
    return payload, detail

def select_source(session_id: str, source: str) -> dict[str, Any]:
    payload = _read(session_id)
    if source not in {"original", "pixelized"}:
        raise ValueError("source must be original or pixelized")
    if source == "pixelized" and payload.get("pixelize_strategy") in {
        "reference_pixel_master_128",
        "identity_preserving_auto",
        "c1",
        "c2",
        "d1",
        "d2",
    }:
        raise ValueError(
            "legacy semantic Pixel Master is not accepted; choose the original source "
            "or rerun deterministic Preserve Pixelize first"
        )
    if source == "pixelized" and payload.get("pixelize_accepted") == "validation_failed":
        raise ValueError(
            "the latest Preserve Pixelize output failed validation; choose the original source "
            "or rerun Pixelize after correcting the input/options"
        )
    pixelized_relative = str(payload.get("pixelized_source") or "pixelized/source.png")
    if source == "pixelized" and not (_session_dir(session_id) / pixelized_relative).is_file():
        raise ValueError("pixelized source is not ready; run Pixelize first")
    payload["source_selection"] = source
    _write(session_id, payload)
    return payload


def _direction_config(count: int) -> tuple[tuple[str, ...], dict[str, str]]:
    if count == 1:
        return ("side",), {}
    if count == 4:
        return ("down", "right", "up", "left"), {}
    return ("down", "front-right", "right", "back-right", "up", "back-left", "left", "front-left"), {}


def _motion_config(body: Any) -> tuple[str, str, bool]:
    if body.motion == "custom":
        text = str(body.custom_motion or "").strip()
        if not text:
            raise ValueError("custom motion requires a description")
        safe = re.sub(r"[^A-Za-z0-9_-]+", "-", text.lower()).strip("-")[:32] or "custom"
        return safe, text, False
    actions = {
        "idle": "subtle breathing and blinking, readable neutral idle",
        "walk": "readable walking cycle with alternating foot contacts",
        "run": "readable running cycle with alternating foot contacts",
        "jump": "anticipation, lift, airborne peak, descent, settle",
        "attack": "clear windup, strike, and recovery attack motion",
        "hurt": "readable hit reaction while preserving the same identity",
    }
    return body.motion, actions[body.motion], body.motion in {"idle", "walk", "run"}


def make_sprite(session_id: str, body: Any) -> tuple[dict[str, Any], str, str, str]:
    payload = _read(session_id)
    if body.pixelize:
        payload, _ = pixelize_session(session_id, body)
    selected = body.sprite_source or payload.get("source_selection", "original")
    if selected == "pixelized" and payload.get("pixelize_strategy") in {
        "reference_pixel_master_128",
        "identity_preserving_auto",
        "c1",
        "c2",
        "d1",
        "d2",
    }:
        raise RuntimeError(
            "legacy semantic Pixel Master is not accepted; choose the original source "
            "or rerun deterministic Preserve Pixelize first"
        )
    if selected == "pixelized" and payload.get("pixelize_accepted") == "validation_failed":
        raise RuntimeError(
            "the latest Preserve Pixelize output failed validation; choose the original source "
            "or rerun Pixelize after correcting the input/options"
        )
    if selected == "pixelized" and not payload.get("pixelized_source"):
        payload, _ = pixelize_session(session_id, body)
    source = _session_dir(session_id) / (Path(str(payload.get("pixelized_source") or "pixelized/source.png")) if selected == "pixelized" else Path("source") / "original.png")
    if not source.is_file():
        raise FileNotFoundError(f"selected quick source is missing: {source}")
    payload["source_selection"] = selected
    directions, mirrors = _direction_config(int(body.directions))
    pose, action, loop = _motion_config(body)
    state_specs = {pose: {"frames": int(body.frames), "fps": 8, "loop": loop, "action": action}}
    run_id = f"quick-{session_id}-{uuid4().hex[:6]}"
    identity = payload.get("prompt") or "the attached source character"
    if payload.get("notes"):
        identity = f"{identity}; operator notes: {payload['notes']}"
    config = StudioRunConfig(
        run_id=run_id,
        character_id="quick-source",
        provider=payload["provider"],
        base_image=source,
        directions=directions,
        mirrors=mirrors,
        states=state_specs,
        cell_size=256,
        runtime_size=48,
        preset="sword",
        description=str(payload.get("prompt") or "Source-first Quick Generate sprite"),
        generation_profile="refine_first",
        background_policy="transparent" if payload.get("background") == "transparent" else "magenta",
    )
    info = run_manager.create_run(config)
    metadata_path = info.path / "studio" / "studio.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["config"].update({
        "quick_session_id": session_id,
        "quick_prompt": identity,
        "quick_style": payload.get("style"),
        "quick_source_selection": selected,
    })
    atomic_write_text(metadata_path, json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
    request = json.loads((info.path / "sprite-request.json").read_text(encoding="utf-8"))
    for state in info.states:
        write_assembled_prompt(
            info.path,
            request,
            state,
            profile=info.generation_profile,
            background_policy=info.background_policy,
        )
    target_state = next((state for state in info.states if state.endswith("_" + pose)), info.states[0])
    job_id = job_service.start_job(
        info.path,
        "quick_make",
        state=target_state,
        options={"states": list(info.states), "strategy": body.generation_strategy, "target_state": target_state},
    )
    payload["run_id"] = run_id
    payload["job_id"] = job_id
    _write(session_id, payload)
    return payload, run_id, target_state, job_id
