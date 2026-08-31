# SPDX-License-Identifier: Apache-2.0
"""Non-destructive Refined → Repair orchestration and persisted review data."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any
from uuid import uuid4

from PIL import Image, ImageDraw

from sprite_studio.spec.layout import frames_dir_rel
from sprite_studio.spec.runio import atomic_save_image, atomic_write_text
from studio.core.repair import RepairCandidate, RepairPipeline, RepairProfile
from studio.core.repair.ai_micro_fix import normalize_and_validate_micro_fix

from .spritegen_bridge import request_for


_JOB_ID = re.compile(r"^[0-9a-f]{16}$")


def _state_dir(run_dir: Path, request: dict[str, Any], state: str) -> Path:
    return run_dir / frames_dir_rel(request, state)


def _repair_dir(run_dir: Path, request: dict[str, Any], state: str) -> Path:
    return _state_dir(run_dir, request, state) / "repair"


def _metadata(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "studio" / "studio.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def _profile(run_dir: Path) -> RepairProfile:
    default_path = Path(__file__).parents[1] / "data" / "repair" / "default.json"
    config = json.loads(default_path.read_text(encoding="utf-8"))
    config.update(((_metadata(run_dir).get("config") or {}).get("repair") or {}))
    return RepairProfile.from_mapping(config)


def _refined_files(run_dir: Path, request: dict[str, Any], state: str) -> list[Path]:
    directory = _state_dir(run_dir, request, state) / "refined"
    files = sorted(directory.glob("frame-*.png")) if directory.is_dir() else []
    if not files:
        raise FileNotFoundError(f"refine first: no refined frames for {state}")
    return files


def _revision(files: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in files:
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()[:24]


def _relative(run_dir: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(run_dir.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _load_logical(run_dir: Path, request: dict[str, Any], state: str) -> tuple[list[Image.Image], list[Path], tuple[int, int]]:
    source_files = _refined_files(run_dir, request, state)
    state_dir = _state_dir(run_dir, request, state)
    report_path = state_dir / "refined" / "refine.report.json"
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.is_file() else {}
    logical = ((report.get("shared") or {}).get("logical_size") or [])
    with Image.open(source_files[0]) as first:
        source_size = first.size
    logical_size = (int(logical[0]), int(logical[1])) if len(logical) == 2 else source_size
    frames: list[Image.Image] = []
    for path in source_files:
        with Image.open(path) as opened:
            rgba = opened.convert("RGBA")
            frames.append(rgba.resize(logical_size, Image.Resampling.NEAREST) if rgba.size != logical_size else rgba.copy())
    return frames, source_files, source_size


def _scale(frame: Image.Image, size: tuple[int, int]) -> Image.Image:
    return frame.resize(size, Image.Resampling.NEAREST) if frame.size != size else frame.copy()


def _candidate_overlay(frame: Image.Image, candidates: list[RepairCandidate], size: tuple[int, int]) -> Image.Image:
    overlay = frame.convert("RGBA").copy()
    draw = ImageDraw.Draw(overlay)
    for candidate in candidates:
        color = (48, 220, 100, 255) if candidate.action == "add" else (255, 70, 70, 255)
        for x, y in candidate.pixels:
            draw.point((x, y), fill=color)
    return _scale(overlay, size)


def analyze_state(run_dir: Path, state: str) -> dict[str, Any]:
    request = request_for(run_dir)
    if state not in request.get("states", {}):
        raise ValueError(f"unknown state: {state}")
    frames, source_files, source_size = _load_logical(run_dir, request, state)
    profile = _profile(run_dir)
    candidates = RepairPipeline().analyze(frames, state=state, profile=profile)
    repair_dir = _repair_dir(run_dir, request, state)
    repair_dir.mkdir(parents=True, exist_ok=True)
    overlay_dir = repair_dir / "proposals"
    if overlay_dir.is_dir():
        shutil.rmtree(overlay_dir)
    overlay_dir.mkdir(parents=True, exist_ok=True)
    for index, frame in enumerate(frames):
        overlay = _candidate_overlay(frame, [item for item in candidates if item.frame == index], source_size)
        atomic_save_image(overlay, overlay_dir / f"frame-{index}.png")
    payload = {
        "kind": "sprite-studio-repair-analysis",
        "version": 1,
        "state": state,
        "source": "refined",
        "source_revision": _revision(source_files),
        "source_files": [_relative(run_dir, path) for path in source_files],
        "logical_size": list(frames[0].size),
        "working_size": list(source_size),
        "profile": {
            "safe_thresholds": profile.safe_thresholds,
            "max_hole_pixels": profile.max_hole_pixels,
            "max_orphan_pixels": profile.max_orphan_pixels,
            "temporal_search_radius": profile.temporal_search_radius,
        },
        "candidate_count": len(candidates),
        "candidates": [candidate.to_dict() for candidate in candidates],
    }
    atomic_write_text(repair_dir / "repair.proposals.json", json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return payload


def _diff_overlay(before: Image.Image, after: Image.Image, changes: list[dict[str, Any]],
                  frame_index: int, size: tuple[int, int]) -> Image.Image:
    overlay = before.convert("RGBA").copy()
    draw = ImageDraw.Draw(overlay)
    for change in changes:
        if int(change["frame"]) != frame_index:
            continue
        color = (48, 220, 100, 255) if change["action"] == "add" else (255, 70, 70, 255)
        for x, y in change["pixels"]:
            draw.point((int(x), int(y)), fill=color)
    return _scale(overlay, size)


def _complete_diff_overlay(before: Image.Image, after: Image.Image, size: tuple[int, int]) -> Image.Image:
    overlay = before.convert("RGBA").copy()
    draw = ImageDraw.Draw(overlay)
    for y in range(before.height):
        for x in range(before.width):
            old = before.getpixel((x, y))
            new = after.getpixel((x, y))
            if old == new:
                continue
            if old[3] == 0 and new[3] > 0:
                color = (48, 220, 100, 255)
            elif old[3] > 0 and new[3] == 0:
                color = (255, 70, 70, 255)
            else:
                color = (255, 205, 40, 255)
            draw.point((x, y), fill=color)
    return _scale(overlay, size)


def repair_state(run_dir: Path, state: str, *, candidate_ids: set[str] | None = None) -> dict[str, Any]:
    request = request_for(run_dir)
    frames, source_files, source_size = _load_logical(run_dir, request, state)
    profile = _profile(run_dir)
    result = RepairPipeline().repair(frames, state=state, profile=profile, candidate_ids=candidate_ids)
    state_dir = _state_dir(run_dir, request, state)
    repaired_dir = state_dir / "repaired"
    if repaired_dir.is_dir():
        shutil.rmtree(repaired_dir)
    repaired_dir.mkdir(parents=True, exist_ok=True)
    repair_dir = _repair_dir(run_dir, request, state)
    diff_dir = repair_dir / "diff"
    if diff_dir.is_dir():
        shutil.rmtree(diff_dir)
    diff_dir.mkdir(parents=True, exist_ok=True)
    changes = [change.to_dict() for change in result.changes]
    output_paths = [repaired_dir / f"frame-{index}.png" for index in range(len(result.frames))]
    for index, (before, repaired) in enumerate(zip(frames, result.frames)):
        atomic_save_image(_scale(repaired, source_size), output_paths[index])
        atomic_save_image(_diff_overlay(before, repaired, changes, index, source_size), diff_dir / f"frame-{index}.png")
    payload = {
        "kind": "sprite-studio-repair-log",
        "version": 1,
        "state": state,
        "source": "refined",
        "source_revision": _revision(source_files),
        "source_files": [_relative(run_dir, path) for path in source_files],
        "output_files": [_relative(run_dir, path) for path in output_paths],
        "output_revision": _revision(output_paths),
        "logical_size": list(frames[0].size),
        "working_size": list(source_size),
        "mode": "selected" if candidate_ids is not None else "safe",
        **result.to_dict(),
    }
    repair_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_text(repair_dir / "repair.log.json", json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return payload


def _decision_path(run_dir: Path, request: dict[str, Any], state: str) -> Path:
    return _repair_dir(run_dir, request, state) / "repair.decisions.json"


def _load_decisions(run_dir: Path, request: dict[str, Any], state: str) -> dict[str, list[str]]:
    path = _decision_path(run_dir, request, state)
    if not path.is_file():
        return {"accepted": [], "rejected": []}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"accepted": [], "rejected": []}
    return {"accepted": list(value.get("accepted") or []), "rejected": list(value.get("rejected") or [])}


def decide_candidates(run_dir: Path, state: str, candidate_ids: set[str], *, accept: bool) -> dict[str, Any]:
    request = request_for(run_dir)
    analysis = analyze_state(run_dir, state)
    known = {str(candidate["id"]) for candidate in analysis["candidates"]}
    unknown = candidate_ids - known
    if unknown:
        raise ValueError(f"unknown or stale repair candidate(s): {', '.join(sorted(unknown))}")
    decisions = _load_decisions(run_dir, request, state)
    accepted = set(decisions["accepted"])
    rejected = set(decisions["rejected"])
    if accept:
        accepted.update(candidate_ids)
        rejected.difference_update(candidate_ids)
    else:
        rejected.update(candidate_ids)
        accepted.difference_update(candidate_ids)
    path = _decision_path(run_dir, request, state)
    atomic_write_text(path, json.dumps({
        "kind": "sprite-studio-repair-decisions", "version": 1, "state": state,
        "source_revision": analysis["source_revision"],
        "accepted": sorted(accepted), "rejected": sorted(rejected),
    }, ensure_ascii=False, indent=2) + "\n")
    log_path = _repair_dir(run_dir, request, state) / "repair.log.json"
    current_ids: set[str] = set()
    if log_path.is_file():
        try:
            current_ids = {str(change["candidate_id"]) for change in json.loads(log_path.read_text(encoding="utf-8")).get("changes", [])}
        except json.JSONDecodeError:
            current_ids = set()
    selected = (current_ids | accepted) - rejected
    return repair_state(run_dir, state, candidate_ids=selected)


def repaired_files(run_dir: Path, state: str) -> list[Path]:
    request = request_for(run_dir)
    try:
        source_files = _refined_files(run_dir, request, state)
    except FileNotFoundError:
        return []
    log_path = _repair_dir(run_dir, request, state) / "repair.log.json"
    if not log_path.is_file():
        return []
    try:
        log = json.loads(log_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    if log.get("source_revision") != _revision(source_files):
        return []
    outputs = [Path(path) if Path(path).is_absolute() else run_dir / path for path in log.get("output_files", [])]
    if not outputs or not all(path.is_file() for path in outputs):
        return []
    if log.get("output_revision") != _revision(outputs):
        return []
    return outputs


def adopt_repaired(run_dir: Path, state: str) -> dict[str, Any]:
    """Make the current repaired output the curation/export source for one state."""
    from copy import deepcopy

    from sprite_studio.curate.curation import empty_curation, load_curation_report, write_curation_atomic
    from sprite_studio.spec.runio import publish_guard

    request = request_for(run_dir)
    if state not in request.get("states", {}):
        raise ValueError(f"unknown state: {state}")
    outputs = repaired_files(run_dir, state)
    if not outputs:
        raise ValueError(f"no current repaired output is available for {state}")
    log_path = _repair_dir(run_dir, request, state) / "repair.log.json"
    log = json.loads(log_path.read_text(encoding="utf-8"))
    output_revision = log.get("output_revision")
    if not isinstance(output_revision, str):
        raise ValueError(f"repair log for {state} has no output revision")
    with publish_guard(run_dir):
        current, _report = load_curation_report(run_dir)
        document = deepcopy(current or empty_curation())
        slot = document.setdefault("states", {}).setdefault(state, {})
        slot["source_variant"] = "repaired"
        slot["source_variant_revision"] = output_revision
        write_curation_atomic(run_dir, document)
    return {"state": state, "source_variant": "repaired", "output_revision": output_revision,
            "output_files": [_relative(run_dir, path) for path in outputs]}


def unadopt_repaired(run_dir: Path, state: str) -> dict[str, Any]:
    """Return one state to the canonical pixel/plain curation source."""
    from copy import deepcopy

    from sprite_studio.curate.curation import empty_curation, load_curation_report, write_curation_atomic
    from sprite_studio.spec.runio import publish_guard

    request = request_for(run_dir)
    if state not in request.get("states", {}):
        raise ValueError(f"unknown state: {state}")
    with publish_guard(run_dir):
        current, _report = load_curation_report(run_dir)
        document = deepcopy(current or empty_curation())
        slot = document.setdefault("states", {}).setdefault(state, {})
        slot.pop("source_variant", None)
        slot.pop("source_variant_revision", None)
        write_curation_atomic(run_dir, document)
    return {"state": state, "source_variant": "canonical"}


def _current_logical_frames(run_dir: Path, request: dict[str, Any], state: str,
                            logical_size: tuple[int, int]) -> list[Image.Image]:
    current = repaired_files(run_dir, state)
    if current:
        frames: list[Image.Image] = []
        for path in current:
            with Image.open(path) as opened:
                frames.append(opened.convert("RGBA").resize(logical_size, Image.Resampling.NEAREST))
        return frames
    frames, _sources, _working = _load_logical(run_dir, request, state)
    return frames


def prepare_ai_micro_fix(run_dir: Path, state: str, candidate_ids: set[str]) -> dict[str, Any]:
    """Export one exact logical frame + mask for an optional external AI editor."""
    if not candidate_ids:
        raise ValueError("select at least one repair candidate for AI Micro Fix")
    request = request_for(run_dir)
    analysis = analyze_state(run_dir, state)
    by_id = {str(item["id"]): item for item in analysis["candidates"]}
    unknown = candidate_ids - set(by_id)
    if unknown:
        raise ValueError(f"unknown or stale repair candidate(s): {', '.join(sorted(unknown))}")
    candidates = [by_id[candidate_id] for candidate_id in sorted(candidate_ids)]
    frame_indices = {int(item["frame"]) for item in candidates}
    if len(frame_indices) != 1:
        raise ValueError("one AI Micro Fix job may target only one frame")
    frame_index = frame_indices.pop()
    logical_size = tuple(int(value) for value in analysis["logical_size"])
    frames = _current_logical_frames(run_dir, request, state, logical_size)
    if not (0 <= frame_index < len(frames)):
        raise ValueError(f"frame index out of range: {frame_index}")
    before = frames[frame_index]
    mask = Image.new("L", before.size, 0)
    mask_pixels = mask.load()
    for candidate in candidates:
        for x, y in candidate.get("pixels") or []:
            if 0 <= int(x) < before.width and 0 <= int(y) < before.height:
                mask_pixels[int(x), int(y)] = 255
    if mask.getbbox() is None:
        raise ValueError("selected repair candidates produced an empty mask")
    job_id = uuid4().hex[:16]
    job_dir = _repair_dir(run_dir, request, state) / "ai-micro-fix" / job_id
    job_dir.mkdir(parents=True, exist_ok=False)
    before_path = job_dir / "before.png"
    mask_path = job_dir / "mask.png"
    atomic_save_image(before, before_path)
    atomic_save_image(mask, mask_path)
    log_path = _repair_dir(run_dir, request, state) / "repair.log.json"
    try:
        repair_log = json.loads(log_path.read_text(encoding="utf-8")) if log_path.is_file() else {}
    except json.JSONDecodeError:
        repair_log = {}
    palette = sorted({color for frame in frames for color in frame.get_flattened_data() if color[3] > 0})
    instruction = (
        "Repair only the white pixels in mask.png. Preserve every unmasked pixel exactly. "
        "Use only colors listed in request.json. Preserve dimensions and binary alpha. "
        f"Resolve: {', '.join(sorted({item['type'] for item in candidates}))}."
    )
    payload = {
        "kind": "sprite-studio-ai-micro-fix-job",
        "version": 1,
        "job_id": job_id,
        "state": state,
        "frame": frame_index,
        "source_revision": analysis["source_revision"],
        "base_output_revision": repair_log.get("output_revision"),
        "candidate_ids": sorted(candidate_ids),
        "candidate_types": sorted({str(item["type"]) for item in candidates}),
        "logical_size": list(before.size),
        "palette": [list(color) for color in palette],
        "before": "before.png",
        "mask": "mask.png",
        "result": "result.png",
        "instruction": instruction,
    }
    atomic_write_text(job_dir / "request.json", json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    atomic_write_text(job_dir / "instruction.txt", instruction + "\n")
    return payload | {"job_dir": str(job_dir), "before_path": str(before_path), "mask_path": str(mask_path)}


def apply_ai_micro_fix(run_dir: Path, state: str, job_id: str, result_path: Path) -> dict[str, Any]:
    """Validate and merge a completed masked job into the derived repaired set."""
    if not _JOB_ID.fullmatch(job_id or ""):
        raise ValueError("invalid AI Micro Fix job id")
    request = request_for(run_dir)
    job_dir = _repair_dir(run_dir, request, state) / "ai-micro-fix" / job_id
    job_path = job_dir / "request.json"
    if not job_path.is_file():
        raise FileNotFoundError(f"AI Micro Fix job not found: {job_id}")
    job = json.loads(job_path.read_text(encoding="utf-8"))
    if job.get("state") != state or job.get("job_id") != job_id:
        raise ValueError("AI Micro Fix job identity does not match the selected state")
    frames, source_files, source_size = _load_logical(run_dir, request, state)
    if job.get("source_revision") != _revision(source_files):
        raise ValueError("AI Micro Fix job is stale because refined source frames changed")
    logical_size = tuple(int(value) for value in job["logical_size"])
    current_log_path = _repair_dir(run_dir, request, state) / "repair.log.json"
    try:
        current_log = json.loads(current_log_path.read_text(encoding="utf-8")) if current_log_path.is_file() else {}
    except json.JSONDecodeError:
        current_log = {}
    if job.get("base_output_revision") != current_log.get("output_revision"):
        raise ValueError("AI Micro Fix job is stale because repaired output changed")
    current = _current_logical_frames(run_dir, request, state, logical_size)
    frame_index = int(job["frame"])
    with Image.open(job_dir / str(job["before"])) as opened:
        before = opened.convert("RGBA")
    if list(before.get_flattened_data()) != list(current[frame_index].get_flattened_data()):
        raise ValueError("AI Micro Fix base frame no longer matches the current repaired frame")
    with Image.open(job_dir / str(job["mask"])) as opened:
        mask = opened.convert("L")
    with Image.open(result_path) as opened:
        proposed = opened.convert("RGBA")
    palette = {tuple(int(channel) for channel in color) for color in job.get("palette") or []}
    fixed = normalize_and_validate_micro_fix(before, proposed, mask, palette)
    changed = [(x, y) for y in range(before.height) for x in range(before.width)
               if before.getpixel((x, y)) != fixed.getpixel((x, y))]
    if not changed:
        raise ValueError("AI Micro Fix result contains no changed pixels")
    current[frame_index] = fixed
    repaired_dir = _state_dir(run_dir, request, state) / "repaired"
    repaired_dir.mkdir(parents=True, exist_ok=True)
    output_paths = [repaired_dir / f"frame-{index}.png" for index in range(len(current))]
    for frame, path in zip(current, output_paths):
        atomic_save_image(_scale(frame, source_size), path)
    diff_dir = _repair_dir(run_dir, request, state) / "diff"
    diff_dir.mkdir(parents=True, exist_ok=True)
    for index, (refined, repaired) in enumerate(zip(frames, current)):
        atomic_save_image(_complete_diff_overlay(refined, repaired, source_size), diff_dir / f"frame-{index}.png")
    imported_result = job_dir / "result.png"
    atomic_save_image(fixed, imported_result)
    added = sum(before.getpixel(point)[3] == 0 and fixed.getpixel(point)[3] > 0 for point in changed)
    removed = sum(before.getpixel(point)[3] > 0 and fixed.getpixel(point)[3] == 0 for point in changed)
    recolored = len(changed) - added - removed
    micro_entry = {
        "job_id": job_id,
        "engine": "ai_micro_fix",
        "frame": frame_index,
        "candidate_ids": list(job.get("candidate_ids") or []),
        "pixels": [list(point) for point in changed],
        "pixels_changed": len(changed),
        "pixels_added": added,
        "pixels_removed": removed,
        "pixels_recolored": recolored,
        "mask_pixels": sum(value > 0 for value in mask.get_flattened_data()),
    }
    payload = dict(current_log) if current_log else {
        "kind": "sprite-studio-repair-log", "version": 1, "state": state,
        "source": "refined", "changes": [], "skipped": [], "candidate_count": 0,
    }
    payload.update({
        "source_revision": _revision(source_files),
        "source_files": [_relative(run_dir, path) for path in source_files],
        "output_files": [_relative(run_dir, path) for path in output_paths],
        "output_revision": _revision(output_paths),
        "logical_size": list(logical_size),
        "working_size": list(source_size),
        "mode": "ai-micro-fix",
    })
    payload.setdefault("ai_micro_fixes", []).append(micro_entry)
    for candidate_id in job.get("candidate_ids") or []:
        payload.setdefault("changes", []).append({
            "candidate_id": str(candidate_id), "frame": frame_index,
            "engine": "ai_micro_fix", "rule": "masked_local_fix", "action": "micro_fix",
            "pixels": [list(point) for point in changed], "pixels_changed": len(changed),
            "confidence": None,
        })
    atomic_write_text(current_log_path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return payload | {"ai_micro_fix": micro_entry}


def clear_repairs(run_dir: Path, state: str) -> None:
    """Discard derived repair outputs only; refined/extracted truth is untouched."""
    request = request_for(run_dir)
    state_dir = _state_dir(run_dir, request, state)
    curation_path = run_dir / "curation.json"
    if curation_path.is_file():
        try:
            slot = (json.loads(curation_path.read_text(encoding="utf-8")).get("states") or {}).get(state) or {}
        except json.JSONDecodeError:
            slot = {}
        if slot.get("source_variant") == "repaired":
            unadopt_repaired(run_dir, state)
    for path in (state_dir / "repair", state_dir / "repaired"):
        if path.is_dir():
            shutil.rmtree(path)


def review_data(run_dir: Path, state: str) -> dict[str, Any]:
    request = request_for(run_dir)
    repair_dir = _repair_dir(run_dir, request, state)
    proposals_path = repair_dir / "repair.proposals.json"
    payload = json.loads(proposals_path.read_text(encoding="utf-8")) if proposals_path.is_file() else None
    if payload is not None:
        try:
            if payload.get("source_revision") != _revision(_refined_files(run_dir, request, state)):
                payload = None
        except FileNotFoundError:
            payload = None
    candidates = payload.get("candidates", []) if payload else []
    repaired = repaired_files(run_dir, state)
    decisions = _load_decisions(run_dir, request, state)
    adopted = False
    adoption_stale = False
    curation_path = run_dir / "curation.json"
    if curation_path.is_file():
        try:
            entry = (json.loads(curation_path.read_text(encoding="utf-8")).get("states") or {}).get(state) or {}
            if entry.get("source_variant") == "repaired":
                log_path = repair_dir / "repair.log.json"
                log = json.loads(log_path.read_text(encoding="utf-8")) if log_path.is_file() else {}
                adopted = entry.get("source_variant_revision") == log.get("output_revision") and bool(repaired)
                adoption_stale = not adopted
        except json.JSONDecodeError:
            adopted = False
    return {
        "candidates": candidates,
        "candidate_choices": [(f"F{item['frame']:02d} {item['type']} {item['confidence']:.2f}", item["id"])
                              for item in candidates],
        "proposal_files": [str(path) for path in sorted((repair_dir / "proposals").glob("frame-*.png"))],
        "repaired_files": [str(path) for path in repaired],
        "diff_files": [str(path) for path in sorted((repair_dir / "diff").glob("frame-*.png"))],
        "decisions": decisions,
        "adopted": adopted,
        "adoption_stale": adoption_stale,
    }


def summary(run_dir: Path, state: str) -> str:
    data = review_data(run_dir, state)
    count = len(data["candidates"])
    if not count:
        return "Repair Analyze를 실행하면 국소 결함 후보가 표시됩니다."
    safe = sum(not item.get("protected") and item["confidence"] >= _profile(run_dir).safe_thresholds.get(item["type"], 1.01)
               for item in data["candidates"])
    repaired = len(data["repaired_files"])
    if data["adopted"]:
        adopted = " · **CURATION/EXPORT ADOPTED**"
    elif data["adoption_stale"]:
        adopted = " · ⚠ **ADOPTION STALE — RE-ADOPT OR REVERT**"
    else:
        adopted = ""
    return f"Repair candidates: **{count}** · safe: **{safe}** · repaired frames: **{repaired}**{adopted}"
