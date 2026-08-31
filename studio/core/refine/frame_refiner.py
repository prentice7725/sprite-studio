# SPDX-License-Identifier: Apache-2.0
"""Deterministic frame refinement with character-level shared locks.

This is the first Studio refine stage. It consumes extracted cell-sized RGBA
frames and writes a derived ``refined/`` set; the engine's canonical frames
remain untouched. Existing pixel-unfake primitives are reused through their
Python Module seam rather than copied.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from sprite_studio.frames.extract import apply_palette, build_shared_palette, enforce_outline
from sprite_studio.spec.runio import atomic_save_image, atomic_write_text


@dataclass(frozen=True)
class RefineResult:
    state: str
    source_files: tuple[str, ...]
    output_files: tuple[str, ...]
    report: dict[str, Any]


class FrameRefiner:
    """Refine a frame set using one shared geometry/grid/palette decision."""

    def refine(
        self,
        frames: list[Image.Image],
        *,
        cell_width: int,
        cell_height: int,
        safe_margin_x: int,
        safe_margin_y: int,
        state: str,
        locks: dict[str, str] | None = None,
        palette_colors: int = 16,
        logical_height: int | None = None,
        outline_strength: float = 0.62,
    ) -> tuple[list[Image.Image], dict[str, Any]]:
        if not frames:
            raise ValueError("cannot refine an empty frame set")
        if any(frame.size != (cell_width, cell_height) for frame in frames):
            raise ValueError("all extracted frames must match the working cell size")
        locks = dict(locks or {})
        bboxes = [frame.getchannel("A").getbbox() for frame in frames]
        if any(bbox is None for bbox in bboxes):
            raise ValueError(f"{state}: empty frame cannot enter refine stage")
        valid = [bbox for bbox in bboxes if bbox is not None]
        max_width = max(bbox[2] - bbox[0] for bbox in valid)
        max_height = max(bbox[3] - bbox[1] for bbox in valid)
        available_width = max(1, cell_width - safe_margin_x * 2)
        available_height = max(1, cell_height - safe_margin_y * 2)
        shared_scale = min(1.0, available_width / max_width, available_height / max_height)
        baseline_y = cell_height - safe_margin_y
        placed: list[Image.Image] = []
        for frame, bbox in zip(frames, valid):
            cropped = frame.crop(bbox)
            size = (max(1, round(cropped.width * shared_scale)), max(1, round(cropped.height * shared_scale)))
            sprite = cropped.resize(size, Image.Resampling.NEAREST)
            left = max(0, (cell_width - sprite.width) // 2)
            top = max(0, round(baseline_y - sprite.height))
            canvas = Image.new("RGBA", (cell_width, cell_height), (0, 0, 0, 0))
            canvas.alpha_composite(sprite, (left, top))
            placed.append(canvas)

        grid_scale = 1
        if logical_height and logical_height > 0 and cell_height % logical_height == 0:
            grid_scale = max(1, cell_height // logical_height)
        logical_width = max(1, math.ceil(cell_width / grid_scale))
        grid_locked: list[Image.Image] = []
        for frame in placed:
            if grid_scale == 1:
                grid_locked.append(frame)
                continue
            logical = frame.resize((logical_width, logical_height or cell_height), Image.Resampling.NEAREST)
            grid_locked.append(logical.resize((cell_width, cell_height), Image.Resampling.NEAREST))

        palette = build_shared_palette(grid_locked, max(2, palette_colors))
        refined = [apply_palette(frame, palette) for frame in grid_locked]
        if outline_strength > 0:
            refined = [enforce_outline(frame, outline_strength) for frame in refined]
        report = {
            "kind": "sprite-studio-frame-refine",
            "state": state,
            "frame_count": len(refined),
            "locks": {
                "grid": locks.get("grid", "state"),
                "palette": locks.get("palette", "character"),
                "baseline": locks.get("baseline", "character"),
                "pivot": locks.get("pivot", "character"),
                "scale": locks.get("scale", "character"),
            },
            "shared": {
                "scale": round(shared_scale, 6),
                "baseline_y": baseline_y,
                "pivot": {"x": 0.5, "y": round(baseline_y / cell_height, 6)},
                "grid_scale": grid_scale,
                "logical_size": [logical_width, logical_height or cell_height],
                "palette_colors": len(palette),
                "palette": [list(color) for color in palette],
            },
        }
        return refined, report


def refine_files(
    source_files: list[Path],
    output_dir: Path,
    *,
    state: str,
    cell_width: int,
    cell_height: int,
    safe_margin_x: int,
    safe_margin_y: int,
    locks: dict[str, str] | None = None,
    palette_colors: int = 16,
    logical_height: int | None = None,
) -> RefineResult:
    with_images = []
    for path in source_files:
        with Image.open(path) as opened:
            with_images.append(opened.convert("RGBA"))
    refined, report = FrameRefiner().refine(
        with_images,
        state=state,
        cell_width=cell_width,
        cell_height=cell_height,
        safe_margin_x=safe_margin_x,
        safe_margin_y=safe_margin_y,
        locks=locks,
        palette_colors=palette_colors,
        logical_height=logical_height,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs: list[str] = []
    for index, image in enumerate(refined):
        path = output_dir / f"frame-{index}.png"
        atomic_save_image(image, path)
        outputs.append(str(path))
    report["source_files"] = [str(path) for path in source_files]
    report["output_files"] = outputs
    atomic_write_text(output_dir / "refine.report.json", __import__("json").dumps(report, ensure_ascii=False, indent=2) + "\n")
    return RefineResult(state, tuple(str(path) for path in source_files), tuple(outputs), report)
