# SPDX-License-Identifier: Apache-2.0
"""Studio orchestration for the Extract → Sprite Refine stage.

Mode dispatch lives here (spec §16.4): a run declares its mode, and the service
hands the frames to that mode's Refine Engine. Sprite Mode runs the v0.2 engine
(shared lattice, bounded phase, continuous weighting, Oklab metric); a project
that pins ``refine.engine = "v1"`` still gets the original ``FrameRefiner``, so
runs produced before the split reproduce byte-for-byte.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Sequence

from PIL import Image

from sprite_studio.spec.layout import frames_dir_rel, row_frame_rel
from sprite_studio.spec.runio import atomic_save_image, atomic_write_text

from studio.core.refine import RefineResult
from studio.core.refine.frame_refiner import refine_files
from studio.shared.config import RefineSettings, apply_overrides, load_refine_settings
from studio.shared.modes import SPRITE, resolve_mode
from studio.sprite_mode.refine import SharedLattice, SpriteRefineEngine, estimate_character_lattice

from .spritegen_bridge import request_for


def _studio_metadata(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "studio" / "studio.json"
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def run_mode(run_dir: Path) -> str:
    """The declared mode of a run. Legacy runs predate the field and are sprite."""
    config = (_studio_metadata(run_dir).get("config") or {})
    return resolve_mode(config.get("mode") or SPRITE).id


def _source_files(run_dir: Path, state: str) -> list[Path]:
    manifest_path = run_dir / "frames" / "frames-manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError("extract first: frames/frames-manifest.json is missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    row = next((item for item in manifest.get("rows", []) if item.get("state") == state), None)
    if not row or not row.get("files"):
        raise ValueError(f"extract first: no extracted frames for {state}")
    return [run_dir / row_frame_rel(row, index) for index in range(len(row["files"]))]


def _load_state_frames(run_dir: Path, state: str) -> list[Image.Image]:
    files = _source_files(run_dir, state)
    frames: list[Image.Image] = []
    for path in files:
        with Image.open(path) as opened:
            frames.append(opened.convert("RGBA"))
    return frames


def estimate_run_character_lattice(
    run_dir: Path,
    states: Sequence[str] | None = None,
    settings: RefineSettings | None = None,
) -> SharedLattice:
    """Estimate a character-scoped shared lattice across all target states in a run."""
    manifest_path = run_dir / "frames" / "frames-manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError("extract first: frames/frames-manifest.json is missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    available_states = [row["state"] for row in manifest.get("rows", []) if row.get("files")]
    target_states = list(states) if states is not None else available_states
    if not target_states:
        raise ValueError("no extracted states available to estimate character lattice")
    
    frames_by_state: dict[str, list[Image.Image]] = {}
    for state in target_states:
        if state in available_states:
            frames_by_state[state] = _load_state_frames(run_dir, state)
    if not frames_by_state:
        raise ValueError(f"no extracted frames found for target states: {target_states}")
    
    config = (_studio_metadata(run_dir).get("config") or {})
    overrides = dict(config.get("refine") or {})
    overrides.pop("engine", None)
    resolved_settings = settings or apply_overrides(load_refine_settings(SPRITE), overrides)
    return estimate_character_lattice(frames_by_state, resolved_settings)


def refine_state(run_dir: Path, state: str, *, shared_lattice: SharedLattice | None = None) -> RefineResult:
    """Refine one state with the engine its mode declares."""
    mode = run_mode(run_dir)
    if mode != SPRITE:
        raise ValueError(f"refine_state is the Sprite Mode path; run {run_dir.name} is {mode!r}")
    request = request_for(run_dir)
    source_files = _source_files(run_dir, state)
    cell = request["cell"]
    config = (_studio_metadata(run_dir).get("config") or {})
    locks = dict(config.get("locks") or {})
    overrides = dict(config.get("refine") or {})
    engine_version = str(overrides.pop("engine", "v2"))
    output_dir = run_dir / frames_dir_rel(request, state) / "refined"
    safe_margin_x = int(cell.get("safe_margin_x", cell.get("safe_margin", 24)))
    safe_margin_y = int(cell.get("safe_margin_y", cell.get("safe_margin", 24)))

    if engine_version == "v1":
        return refine_files(
            source_files,
            output_dir,
            state=state,
            cell_width=int(cell["width"]),
            cell_height=int(cell["height"]),
            safe_margin_x=safe_margin_x,
            safe_margin_y=safe_margin_y,
            locks=locks,
            palette_colors=16,
            logical_height=int(config.get("logical_height", 64)) if config.get("logical_height") else None,
        )
    if engine_version != "v2":
        raise ValueError(f"unknown refine engine {engine_version!r}; expected v1 or v2")

    settings = apply_overrides(load_refine_settings(SPRITE), overrides)
    if shared_lattice is None and settings.lattice.scope == "character":
        shared_lattice = estimate_run_character_lattice(run_dir, settings=settings)

    frames = _load_state_frames(run_dir, state)
    output = SpriteRefineEngine(settings).refine(
        frames,
        state=state,
        cell_width=int(cell["width"]),
        cell_height=int(cell["height"]),
        safe_margin_x=safe_margin_x,
        safe_margin_y=safe_margin_y,
        locks=locks,
        shared_lattice=shared_lattice,
    )
    return _write_refined(output, source_files, output_dir, state)


def refine_states(run_dir: Path, states: Sequence[str]) -> dict[str, RefineResult]:
    """Refine multiple states, estimating character lattice once if scope == 'character'."""
    mode = run_mode(run_dir)
    if mode != SPRITE:
        raise ValueError(f"refine_states is the Sprite Mode path; run {run_dir.name} is {mode!r}")
    config = (_studio_metadata(run_dir).get("config") or {})
    overrides = dict(config.get("refine") or {})
    engine_version = str(overrides.get("engine", "v2"))
    
    shared_lattice: SharedLattice | None = None
    if engine_version == "v2":
        clean_overrides = {k: v for k, v in overrides.items() if k != "engine"}
        settings = apply_overrides(load_refine_settings(SPRITE), clean_overrides)
        if settings.lattice.scope == "character":
            shared_lattice = estimate_run_character_lattice(run_dir, states=states, settings=settings)
            
    results: dict[str, RefineResult] = {}
    for state in states:
        results[state] = refine_state(run_dir, state, shared_lattice=shared_lattice)
    return results


def refine_run(run_dir: Path) -> dict[str, RefineResult]:
    """Refine all extracted states in a run."""
    manifest_path = run_dir / "frames" / "frames-manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError("extract first: frames/frames-manifest.json is missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    states = [row["state"] for row in manifest.get("rows", []) if row.get("files")]
    return refine_states(run_dir, states)


def _write_refined(output, source_files: list[Path], output_dir: Path, state: str) -> RefineResult:
    """Persist refined frames beside the canonical extraction, never over it.

    The logical frames are written too. They are the true-resolution result and
    the only thing a downstream consumer can inspect without undoing the cell
    placement — the placed frames are already upscaled.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    logical_dir = output_dir / "logical"
    logical_dir.mkdir(parents=True, exist_ok=True)
    outputs: list[str] = []
    for index, image in enumerate(output.frames):
        path = output_dir / f"frame-{index}.png"
        atomic_save_image(image, path)
        outputs.append(str(path))
    for index, image in enumerate(output.logical_frames):
        atomic_save_image(image, logical_dir / f"frame-{index}.png")
    report = dict(output.report)
    report["source_files"] = [str(path) for path in source_files]
    report["output_files"] = outputs
    report["logical_files"] = [str(logical_dir / f"frame-{index}.png") for index in range(len(output.logical_frames))]
    atomic_write_text(output_dir / "refine.report.json", json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return RefineResult(state, tuple(str(path) for path in source_files), tuple(outputs), report)


def refine_report(run_dir: Path, state: str) -> dict[str, Any] | None:
    request = request_for(run_dir)
    path = run_dir / frames_dir_rel(request, state) / "refined" / "refine.report.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
