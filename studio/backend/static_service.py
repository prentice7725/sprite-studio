# SPDX-License-Identifier: MIT
"""Static Mode project lifecycle and pipeline (spec §7.3, §11.3).

Static projects are much lighter than sprite runs: there is no row layout, no
frame manifest, no atlas. A project is a directory holding one source image per
asset, its refined logical output, and the reports. That difference is the
reason this is its own service rather than a flag on ``run_manager`` — folding
a scene into a sprite run's scaffolding would mean inventing directions and
states that a background does not have.

    <project>/
      static/project.json          declared config
      raw/<asset>.png              generated / imported source
      refined/<asset>.png          logical output (true resolution)
      refined/<asset>.report.json  refine report
      export/<asset>.png           delivery-size export
      qa/<asset>.json              static QA record
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from sprite_studio.spec.runio import atomic_save_image, atomic_write_text

from studio.shared.config import apply_overrides, load_refine_settings
from studio.shared.modes import STATIC, resolve_asset_type
from studio.static_mode.cleanup import cleanup_scene
from studio.static_mode.layer import compose_layers, cutout_object, split_layers
from studio.static_mode.qa import run_static_qa
from studio.static_mode.refine import StaticRefineEngine
from studio.static_mode.tile import check_seams, repair_seams, wraparound_preview

from .schemas import StaticProjectConfig, StaticProjectInfo


PROJECTS_ROOT_ENV = "SPRITE_STUDIO_STATIC_ROOT"
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


def projects_root(root: Path | None = None) -> Path:
    value = root or Path(os.environ.get(PROJECTS_ROOT_ENV, os.environ.get("SPRITE_STUDIO_RUNS_ROOT", "runs")))
    return value.expanduser().resolve()


def _validate(config: StaticProjectConfig) -> None:
    if not _SAFE_ID.fullmatch(config.project_id):
        raise ValueError("project_id must contain only letters, numbers, '_' or '-' and start alphanumeric")
    if config.provider not in {"grok", "codex"}:
        raise ValueError("provider must be grok or codex")
    width, height = config.export_size
    if width <= 0 or height <= 0:
        raise ValueError("export_size must be positive")


def settings_for(info: StaticProjectInfo):
    """Static refine settings with the project's declared overrides applied."""
    return apply_overrides(load_refine_settings(STATIC), dict(info.refine or {}))


def create_project(config: StaticProjectConfig, *, root: Path | None = None) -> StaticProjectInfo:
    _validate(config)
    base = projects_root(root)
    project_dir = base / config.project_id
    if project_dir.exists() and any(project_dir.iterdir()):
        raise FileExistsError(f"project already exists and is not empty: {project_dir}")
    for name in ("static", "raw", "refined", "export", "qa"):
        (project_dir / name).mkdir(parents=True, exist_ok=True)
    payload = asdict(config) | {
        "base_image": str(config.base_image) if config.base_image else None,
        "export_size": list(config.export_size),
    }
    metadata = {
        "version": 1,
        "kind": "asset-studio-static-project",
        "mode": STATIC,
        "config": payload,
        "project_dir": str(project_dir),
    }
    atomic_write_text(
        project_dir / "static" / "project.json",
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
    )
    if config.base_image:
        with Image.open(config.base_image) as opened:
            atomic_save_image(opened.convert("RGBA"), project_dir / "raw" / "base.png")
    return load_project(config.project_id, root=root)


def load_project(project_id: str, *, root: Path | None = None) -> StaticProjectInfo:
    if not _SAFE_ID.fullmatch(project_id):
        raise ValueError(f"invalid project id: {project_id!r}")
    project_dir = projects_root(root) / project_id
    path = project_dir / "static" / "project.json"
    if not path.is_file():
        raise FileNotFoundError(f"static project not found: {path}")
    metadata = json.loads(path.read_text(encoding="utf-8"))
    config = metadata.get("config") or {}
    export_size = config.get("export_size") or [1024, 1024]
    return StaticProjectInfo(
        project_id=project_id,
        path=project_dir,
        provider=str(config.get("provider", "grok")),
        asset_type=resolve_asset_type(STATIC, config.get("asset_type")),
        style_profile=str(config.get("style_profile", "pixel_scene")),
        tileable=bool(config.get("tileable", False)),
        export_size=(int(export_size[0]), int(export_size[1])),
        description=str(config.get("description", "")),
        layer_intent=str(config.get("layer_intent", "none")),
        background_policy=str(config.get("background_policy", "auto")),
        refine=dict(config.get("refine") or {}),
    )


def list_projects(*, root: Path | None = None) -> list[StaticProjectInfo]:
    base = projects_root(root)
    if not base.is_dir():
        return []
    found: list[StaticProjectInfo] = []
    for path in sorted(base.iterdir()):
        if path.is_dir() and _SAFE_ID.fullmatch(path.name) and (path / "static" / "project.json").is_file():
            try:
                found.append(load_project(path.name, root=root))
            except (OSError, ValueError, json.JSONDecodeError):
                continue
    return found


def import_asset(info: StaticProjectInfo, image_path: Path, *, asset: str = "scene") -> Path:
    """Bring a generated or hand-supplied image into the project as a raw asset."""
    if not _SAFE_ID.fullmatch(asset):
        raise ValueError(f"invalid asset name: {asset!r}")
    target = info.path / "raw" / f"{asset}.png"
    with Image.open(image_path) as opened:
        atomic_save_image(opened.convert("RGBA"), target)
    return target


def raw_assets(info: StaticProjectInfo) -> list[str]:
    directory = info.path / "raw"
    return sorted(path.stem for path in directory.glob("*.png")) if directory.is_dir() else []


def refine_asset(info: StaticProjectInfo, asset: str = "scene", *, cleanup: bool = True) -> dict[str, Any]:
    """Run the Static Refine Engine over one raw asset and persist the result."""
    source = info.path / "raw" / f"{asset}.png"
    if not source.is_file():
        raise FileNotFoundError(f"no raw asset to refine: {source}")
    settings = settings_for(info)
    with Image.open(source) as opened:
        image = opened.convert("RGBA")
    # A tile has to end on a cell boundary or its wrap lands half a block off.
    # The engine does that trim in source space, where the pitch means something.
    output = StaticRefineEngine(settings).refine(
        image, asset_type=info.asset_type, cleanup=cleanup, tile_align=info.tileable
    )
    logical = output.logical
    refined_path = info.path / "refined" / f"{asset}.png"
    atomic_save_image(logical, refined_path)
    report = dict(output.report)
    report["asset"] = asset
    report["source"] = str(source)
    report["output"] = str(refined_path)
    atomic_write_text(
        info.path / "refined" / f"{asset}.report.json",
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
    )
    return report


def refined_image(info: StaticProjectInfo, asset: str = "scene") -> Image.Image:
    path = info.path / "refined" / f"{asset}.png"
    if not path.is_file():
        raise FileNotFoundError(f"refine first: {path} is missing")
    with Image.open(path) as opened:
        return opened.convert("RGBA")


def cleanup_asset(
    info: StaticProjectInfo,
    asset: str = "scene",
    *,
    orphan_max_area: int | None = None,
    fill_max_area: int = 4,
) -> dict[str, Any]:
    """Run Scene Cleanup / Static Repair on a refined asset, in place.

    Separate from refine on purpose (spec section 12.3 gives CLEANUP its own
    section): re-running the whole grid search to try a different speck
    threshold would re-decide the grid too, and an operator tuning cleanup is
    not asking for a new lattice.
    """
    settings = settings_for(info)
    cleanup_settings = settings.cleanup
    if orphan_max_area is not None:
        cleanup_settings = replace(cleanup_settings, orphan_max_area=int(orphan_max_area))
    image = refined_image(info, asset)
    result = cleanup_scene(image, cleanup_settings, fill_max_area=fill_max_area)
    atomic_save_image(result.image, info.path / "refined" / f"{asset}.png")
    report = dict(result.report) | {"asset": asset, "orphan_max_area": cleanup_settings.orphan_max_area}
    atomic_write_text(
        info.path / "qa" / f"{asset}.cleanup.json",
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
    )
    return report


def check_tileability(info: StaticProjectInfo, asset: str = "scene", *, repair: bool = False) -> dict[str, Any]:
    """Seam check, and optionally close the seam. Repair is never implicit."""
    settings = settings_for(info)
    image = refined_image(info, asset)
    report = check_seams(image, settings.seam).to_dict()
    if repair:
        repaired, detail = repair_seams(image, settings.seam)
        atomic_save_image(repaired, info.path / "refined" / f"{asset}.png")
        report["repair"] = detail
    preview_path = info.path / "refined" / f"{asset}.wrap.png"
    atomic_save_image(wraparound_preview(refined_image(info, asset)), preview_path)
    report["wrap_preview"] = str(preview_path)
    atomic_write_text(
        info.path / "qa" / f"{asset}.seam.json",
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
    )
    return report


def process_layers(info: StaticProjectInfo, asset: str = "scene", *, cutout: bool = False) -> dict[str, Any]:
    """Split a scene into layers, or cut one object out of its background."""
    image = refined_image(info, asset)
    layer_dir = info.path / "refined" / f"{asset}.layers"
    layer_dir.mkdir(parents=True, exist_ok=True)
    if cutout:
        result, report = cutout_object(image)
        atomic_save_image(result, layer_dir / "cutout.png")
        report["output"] = str(layer_dir / "cutout.png")
        return report
    layers, report = split_layers(image)
    for layer in layers:
        atomic_save_image(layer.image, layer_dir / f"{layer.name}.png")
    # A split that does not recompose to the input has dropped or duplicated
    # pixels; checking it here means the guarantee is verified, not asserted.
    recomposed = compose_layers(layers, image.size)
    report["round_trips"] = np.array_equal(np.asarray(recomposed), np.asarray(image))
    report["output_dir"] = str(layer_dir)
    atomic_write_text(
        info.path / "qa" / f"{asset}.layers.json",
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
    )
    return report


def static_qa(info: StaticProjectInfo, asset: str = "scene") -> dict[str, Any]:
    settings = settings_for(info)
    image = refined_image(info, asset)
    report_path = info.path / "refined" / f"{asset}.report.json"
    palette: tuple[tuple[int, int, int, int], ...] = ()
    layers: int | None = None
    if report_path.is_file():
        stored = json.loads(report_path.read_text(encoding="utf-8"))
        palette = tuple(tuple(entry) for entry in (stored.get("palette") or {}).get("entries", []))
    layers_report = info.path / "qa" / f"{asset}.layers.json"
    if layers_report.is_file():
        layers = len(json.loads(layers_report.read_text(encoding="utf-8")).get("layers", []))
    result = run_static_qa(
        image, settings, asset_type=info.asset_type, palette=palette,
        tileable=info.tileable, layers=layers,
    )
    payload = result.to_dict() | {"asset": asset}
    atomic_write_text(
        info.path / "qa" / f"{asset}.json",
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
    )
    return payload


def export_asset(info: StaticProjectInfo, asset: str = "scene", *, size: tuple[int, int] | None = None) -> Path:
    """Scale the logical result up to delivery size with NEAREST only.

    Export is where the true-resolution art becomes a delivery file, and the
    only resampling allowed is integer-ish nearest — a smooth filter here would
    undo the entire refine stage at the last step.
    """
    image = refined_image(info, asset)
    target = size or info.export_size
    exported = image.resize(target, Image.Resampling.NEAREST)
    path = info.path / "export" / f"{asset}.png"
    atomic_save_image(exported, path)
    atomic_write_text(
        info.path / "export" / f"{asset}.manifest.json",
        json.dumps(
            {
                "kind": "asset-studio-static-export",
                "asset": asset,
                "asset_type": info.asset_type,
                "logical_size": list(image.size),
                "export_size": list(target),
                "tileable": info.tileable,
                "resample": "nearest",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
    )
    return path


def project_status(info: StaticProjectInfo) -> dict[str, str]:
    """Per-asset pipeline position, for the Static Mode matrix view."""
    statuses: dict[str, str] = {}
    for asset in raw_assets(info):
        qa_path = info.path / "qa" / f"{asset}.json"
        if (info.path / "export" / f"{asset}.png").is_file():
            statuses[asset] = "exported"
        elif qa_path.is_file():
            try:
                statuses[asset] = "refined" if json.loads(qa_path.read_text(encoding="utf-8")).get("ok") else "qa-warning"
            except json.JSONDecodeError:
                statuses[asset] = "failed"
        elif (info.path / "refined" / f"{asset}.png").is_file():
            statuses[asset] = "refined"
        else:
            statuses[asset] = "raw"
    return statuses
