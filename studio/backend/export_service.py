# SPDX-License-Identifier: Apache-2.0
"""Studio export orchestration."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from PIL import Image
from sprite_studio.compose import compose_atlas
from sprite_studio.spec.runio import atomic_save_image, atomic_write_text


def compose(run_dir: Path) -> int:
    return compose_atlas.run(run_dir=run_dir, atlas="sprite-sheet-alpha.png", manifest="manifest.json", report="sprite-sheet-alpha.report.json", min_used_pixels=None)


def build_runtime(run_dir: Path, *, runtime_size: int | None = None) -> dict[str, Any]:
    """Create the fixed-size nearest-neighbor atlas consumed by the game runtime."""
    run_dir = Path(run_dir)
    manifest_path = run_dir / "manifest.json"
    atlas_path = run_dir / "sprite-sheet-alpha.png"
    if not manifest_path.is_file() or not atlas_path.is_file():
        code = compose(run_dir)
        if code != 0:
            raise RuntimeError(f"compose failed with exit code {code}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    with Image.open(atlas_path) as opened:
        source = opened.convert("RGBA")
    cell = manifest.get("cell") or {}
    source_width = int(cell.get("width", cell.get("size", 0)))
    source_height = int(cell.get("height", cell.get("size", 0)))
    if source_width <= 0 or source_height <= 0:
        raise ValueError("manifest.cell must contain positive width and height")
    if runtime_size is None:
        metadata_path = run_dir / "studio" / "studio.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.is_file() else {}
        runtime_size = int((metadata.get("config") or {}).get("runtime_size", 48))
    if runtime_size <= 0:
        raise ValueError("runtime_size must be positive")

    runtime_width = runtime_size
    runtime_height = runtime_size if source_width == source_height else max(1, round(runtime_size * source_height / source_width))
    scale_x = runtime_width / source_width
    scale_y = runtime_height / source_height
    runtime = source.resize((max(1, round(source.width * scale_x)), max(1, round(source.height * scale_y))), Image.Resampling.NEAREST)
    runtime_atlas = run_dir / "runtime-atlas.png"
    runtime_manifest = run_dir / "runtime-manifest.json"
    atomic_save_image(runtime, runtime_atlas)

    result = copy.deepcopy(manifest)
    result["source_atlas"] = manifest.get("sprite_sheet_alpha", "sprite-sheet-alpha.png")
    result["runtime_atlas"] = runtime_atlas.name
    result["sprite_sheet_alpha"] = runtime_atlas.name
    result["cell"] = dict(cell)
    result["cell"].update({"width": runtime_width, "height": runtime_height, "size": runtime_size})
    result["animation"] = dict(result.get("animation") or {})
    result["animation"].update({"cellWidth": runtime_width, "cellHeight": runtime_height})
    layout = dict(result.get("frame_layout") or {})
    layout.update({"sheetWidth": runtime.width, "sheetHeight": runtime.height, "cellWidth": runtime_width, "cellHeight": runtime_height})
    layout_rows: dict[str, list[dict[str, int]]] = {}
    for state, rects in (layout.get("rows") or {}).items():
        layout_rows[state] = [
            {"x": round(int(rect["x"]) * scale_x), "y": round(int(rect["y"]) * scale_y),
             "w": runtime_width, "h": runtime_height}
            for rect in rects
        ]
    layout["rows"] = layout_rows
    result["frame_layout"] = layout
    for row in (result["animation"].get("rows") or {}).values():
        if isinstance(row, dict):
            row["cellWidth"] = runtime_width
            row["cellHeight"] = runtime_height
    atomic_write_text(runtime_manifest, json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return {"atlas": runtime_atlas, "manifest": runtime_manifest, "size": (runtime.width, runtime.height)}
