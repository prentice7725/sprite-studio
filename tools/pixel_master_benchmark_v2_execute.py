#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Execute the local Phase 2A Pixel Master benchmark.

The AI methods consume pre-existing candidate images from ``ai_inputs``. The
runner never creates an AI candidate or a Tier B source fallback. C1/C2 source
references are resolved through the immutable fixture guard before any output
directory is created.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import statistics
import sys
from collections import deque
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from studio.shared.palette import apply_palette, build_palette, opaque_colors
from studio.static_mode.pixelize import PixelizeOptions
from studio.static_mode.pixelize import engine as pixelize_engine
from tools.pixel_master_benchmark_v2 import DEFAULT_CONFIG, V2RunContext, prepare_run
from tools.pixelize_benchmark import _prepare_subject, _run_method


DEFAULT_OUT = ROOT / "benchmark_v2"
AI_INPUT_ROOT = DEFAULT_OUT / "ai_inputs"
SOURCE_FILES = {
    "D01": "D01_front_readable.png",
    "D03": "D03_mascot.png",
    "D06": "D06_weapon.png",
    "D10": "D10_low_contrast.png",
}
METHOD_LABELS = {
    "A1": "A1 deterministic M1.1",
    "A2": "A2 BOX geometry-first",
    "B1": "B1 deterministic DPID/PIA-like",
    "C1": "C1 direct AI pixel-art",
    "C2": "C2 AI style-to-128 redraw",
}


def _options(context: V2RunContext) -> PixelizeOptions:
    return PixelizeOptions(
        target_size=128,
        palette_size=None,
        dither="none",
        background="cleanup",
        outline="preserve",
        alpha_threshold=128,
        subject_mode="auto",
        detail="balanced",
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_path(context: V2RunContext, source_id: str) -> Path:
    if source_id.startswith("R"):
        return context.tier_b_fixtures.path_for(source_id)
    try:
        return ROOT / "benchmark" / "sources" / SOURCE_FILES[source_id]
    except KeyError as exc:
        raise ValueError(f"no Phase 2A source mapping for {source_id}") from exc


def _ai_input_path(ai_root: Path, method_id: str, source_id: str) -> Path:
    return ai_root / method_id / f"{source_id}.png"


def _preflight_ai_inputs(context: V2RunContext, ai_root: Path) -> None:
    missing: list[str] = []
    for source_id in (*context.tier_a_sources, *context.tier_b_sources):
        for method_id in ("C1", "C2"):
            path = _ai_input_path(ai_root, method_id, source_id)
            if not path.is_file():
                missing.append(f"{method_id}/{source_id}: {path}")
    if missing:
        raise FileNotFoundError(
            "Phase 2A AI candidate inputs are missing; no AI fallback is allowed:\n" + "\n".join(missing)
        )


def _palette_post(image: Image.Image) -> Image.Image:
    colors, _ = opaque_colors([image], alpha_threshold=128)
    palette_size = max(8, min(48, int(colors.shape[0]) if colors.size else 8))
    palette = build_palette([image], palette_size, alpha_threshold=128, iterations=6)
    return apply_palette(image, palette, alpha_threshold=128)


def _binary_alpha(image: Image.Image) -> Image.Image:
    rgba = image.convert("RGBA")
    array = np.asarray(rgba, dtype=np.uint8).copy()
    array[:, :, 3] = np.where(array[:, :, 3] >= 128, 255, 0).astype(np.uint8)
    return Image.fromarray(array, "RGBA")


def _remove_isolated_pixels(image: Image.Image) -> Image.Image:
    rgba = _binary_alpha(image)
    array = np.asarray(rgba, dtype=np.uint8).copy()
    alpha = array[:, :, 3] > 0
    isolated = np.zeros_like(alpha)
    isolated[1:-1, 1:-1] = (
        alpha[1:-1, 1:-1]
        & ~alpha[:-2, 1:-1]
        & ~alpha[2:, 1:-1]
        & ~alpha[1:-1, :-2]
        & ~alpha[1:-1, 2:]
    )
    array[isolated, 3] = 0
    return Image.fromarray(array, "RGBA")


def _normalize_subject_canvas(image: Image.Image) -> Image.Image:
    rgba = _binary_alpha(image)
    bbox = rgba.getchannel("A").getbbox()
    if bbox is None:
        return Image.new("RGBA", (128, 128), (0, 0, 0, 0))
    subject = rgba.crop(bbox)
    scale = 128.0 / max(1, subject.height)
    width = max(1, int(round(subject.width * scale)))
    height = 128
    resized = subject.resize((width, height), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
    x = max(0, (128 - resized.width) // 2)
    if resized.width > 128:
        resized = resized.crop(((resized.width - 128) // 2, 0, (resized.width - 128) // 2 + 128, 128))
        x = 0
    canvas.alpha_composite(resized, (x, 0))
    return canvas


def shared_post_process(image: Image.Image) -> Image.Image:
    normalized = _normalize_subject_canvas(image)
    cleaned = _remove_isolated_pixels(normalized)
    return _palette_post(_binary_alpha(cleaned))


def _run_b1(source: Image.Image, options: PixelizeOptions) -> Image.Image:
    subject, _, _, _ = _prepare_subject(source, options)
    logical_size = pixelize_engine._logical_size(subject.size, options.target_size)
    enhanced = subject.filter(ImageFilter.UnsharpMask(radius=1.2, percent=135, threshold=3))
    resized = enhanced.resize(logical_size, Image.Resampling.LANCZOS)
    palette_size = pixelize_engine._auto_palette_size(resized, options.alpha_threshold, options.detail)
    palette = build_palette([resized], palette_size, alpha_threshold=options.alpha_threshold, iterations=8)
    return apply_palette(resized, palette, alpha_threshold=options.alpha_threshold)


def _run_local_method(method_id: str, source: Image.Image, options: PixelizeOptions) -> Image.Image:
    if method_id in ("A1", "A2"):
        mapped = "A1_current_m1_1" if method_id == "A1" else "A2_box"
        return _run_method(mapped, source, options)[0]
    if method_id == "B1":
        return _run_b1(source, options)
    raise ValueError(f"not a local deterministic method: {method_id}")


def _tiny_islands(image: Image.Image) -> int:
    array = np.asarray(image.convert("RGBA"), dtype=np.uint8)
    opaque = array[:, :, 3] > 0
    visited = np.zeros_like(opaque)
    tiny = 0
    height, width = opaque.shape
    for y in range(height):
        for x in range(width):
            if not opaque[y, x] or visited[y, x]:
                continue
            color = array[y, x, :3].copy()
            queue = deque([(x, y)])
            visited[y, x] = True
            size = 0
            while queue:
                cx, cy = queue.popleft()
                size += 1
                for nx, ny in ((cx - 1, cy), (cx + 1, cy), (cx, cy - 1), (cx, cy + 1)):
                    if 0 <= nx < width and 0 <= ny < height and opaque[ny, nx] and not visited[ny, nx] and np.array_equal(array[ny, nx, :3], color):
                        visited[ny, nx] = True
                        queue.append((nx, ny))
            if size <= 2:
                tiny += size
    return tiny


def objective_metrics(image: Image.Image) -> dict[str, Any]:
    rgba = image.convert("RGBA")
    array = np.asarray(rgba, dtype=np.uint8)
    alpha = array[:, :, 3]
    opaque = alpha > 0
    colors = {tuple(color) for color in array[opaque, :3].tolist()}
    bbox = rgba.getchannel("A").getbbox()
    occupied = 0.0 if bbox is None else ((bbox[2] - bbox[0]) * (bbox[3] - bbox[1])) / (rgba.width * rgba.height)
    return {
        "width": rgba.width,
        "height": rgba.height,
        "palette_size": len(colors),
        "alpha_fringe_pixels": int(((alpha > 0) & (alpha < 255)).sum()),
        "isolated_pixel_count": _tiny_islands(rgba),
        "occupied_bbox_ratio": round(occupied, 6),
        "target_height_error": abs((bbox[3] - bbox[1]) - 128) if bbox else 128,
        "sha256": _sha256_bytes(rgba.tobytes()),
    }


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _checkerboard(size: tuple[int, int], cell: int = 16) -> Image.Image:
    image = Image.new("RGBA", size, (238, 238, 238, 255))
    draw = ImageDraw.Draw(image)
    for y in range(0, size[1], cell):
        for x in range(0, size[0], cell):
            if ((x // cell) + (y // cell)) % 2:
                draw.rectangle((x, y, min(size[0] - 1, x + cell - 1), min(size[1] - 1, y + cell - 1)), fill=(208, 208, 208, 255))
    return image


def _tile(path: Path, label: str, size: tuple[int, int] = (220, 260)) -> Image.Image:
    tile = _checkerboard(size)
    with Image.open(path) as opened:
        image = opened.convert("RGBA")
    contained = ImageOps.contain(image, (size[0] - 16, size[1] - 38), method=Image.Resampling.NEAREST)
    tile.alpha_composite(contained, ((size[0] - contained.width) // 2, 8))
    ImageDraw.Draw(tile).text((8, size[1] - 24), label, fill=(20, 20, 24, 255), font=ImageFont.load_default())
    return tile


def _write_sheets(rows: list[dict[str, Any]], sheets_root: Path, source_ids: list[str], method_ids: list[str]) -> None:
    by_source = sheets_root / "by_source"
    by_method = sheets_root / "by_method"
    by_source.mkdir(parents=True, exist_ok=True)
    by_method.mkdir(parents=True, exist_ok=True)
    for source_id in source_ids:
        tiles: list[Image.Image] = []
        for method_id in method_ids:
            pair = [row for row in rows if row["source_id"] == source_id and row["method_id"] == method_id]
            paths = {row["state"]: Path(row["path"]) for row in pair}
            if paths.get("raw") and paths.get("post"):
                tiles.extend([_tile(paths["raw"], f"{method_id} raw"), _tile(paths["post"], f"{method_id} post")])
        columns = 4
        rows_count = max(1, (len(tiles) + columns - 1) // columns)
        sheet = Image.new("RGBA", (columns * 220, rows_count * 260), (250, 250, 250, 255))
        for index, tile in enumerate(tiles):
            sheet.alpha_composite(tile, ((index % columns) * 220, (index // columns) * 260))
        sheet.save(by_source / f"{source_id}.png", format="PNG", optimize=False)
    for method_id in method_ids:
        tiles = []
        for source_id in source_ids:
            post = next((row for row in rows if row["source_id"] == source_id and row["method_id"] == method_id and row["state"] == "post"), None)
            if post:
                tiles.append(_tile(Path(post["path"]), source_id, (180, 220)))
        columns = 4
        rows_count = max(1, (len(tiles) + columns - 1) // columns)
        sheet = Image.new("RGBA", (columns * 180, rows_count * 220), (250, 250, 250, 255))
        for index, tile in enumerate(tiles):
            sheet.alpha_composite(tile, ((index % columns) * 180, (index // columns) * 220))
        sheet.save(by_method / f"{method_id}.png", format="PNG", optimize=False)


def _write_reports(rows: list[dict[str, Any]], reports_root: Path, context: V2RunContext) -> None:
    reports_root.mkdir(parents=True, exist_ok=True)
    (reports_root / "objective_scores.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    fields = ["source_id", "method_id", "state", "path", "width", "height", "palette_size", "alpha_fringe_pixels", "isolated_pixel_count", "occupied_bbox_ratio", "target_height_error", "sha256"]
    with (reports_root / "objective_scores.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows({field: row.get(field) for field in fields} for row in rows)
    human_fields = ["source_id", "method_id", "identity_fidelity", "silhouette_readability", "face_readability", "costume_readability", "asymmetric_feature_preservation", "pixel_cluster_quality", "palette_cleanliness", "outline_quality", "cleanup_burden", "production_readiness", "notes"]
    with (reports_root / "human_scores.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=human_fields)
        writer.writeheader()
        for source_id in (*context.tier_a_sources, *context.tier_b_sources):
            for method_id in context.methods:
                writer.writerow({"source_id": source_id, "method_id": method_id})
    focus = [row for row in rows if row["state"] == "post"]
    means: dict[str, float] = {}
    for method_id in context.methods:
        values = [float(row["palette_size"]) for row in focus if row["method_id"] == method_id]
        if values:
            means[method_id] = round(statistics.mean(values), 3)
    best = min(means, key=means.get) if means else None
    lines = [
        "# Pixel Master Benchmark V2 — Phase 2A Summary",
        "",
        "## Scope",
        "",
        f"- Sources: {len(context.tier_a_sources) + len(context.tier_b_sources)} (Tier A: {', '.join(context.tier_a_sources)}; Tier B: {', '.join(context.tier_b_sources)})",
        f"- Methods: {', '.join(context.methods)}",
        "- Target: 128 logical pixels, Auto palette, Balanced detail",
        "- States: raw and post",
        "- Tier B policy: immutable existing files only; SHA-256 verified before run",
        "",
        "## Execution result",
        "",
        f"- Completed artifacts: {len(rows)} (8 sources × 5 methods × 2 states)",
        f"- Objective post palette-size proxy winner: **{METHOD_LABELS.get(best, best or 'pending human review')}**",
        "- Human review: pending; fill `human_scores.csv` before making a visual-quality promotion decision.",
        "",
        "## Interpretation",
        "",
        "Objective metrics are supporting signals only. The final Preserve and Pixel Master creation recommendations require the human rubric, especially identity, face readability, asymmetric feature preservation, cluster quality, and cleanup burden.",
        "",
        "## Artifacts",
        "",
        "- `raw/<method>/<source>.png` — direct method output",
        "- `post/<method>/<source>.png` — shared normalization, palette, alpha, and isolated-pixel cleanup",
        "- `reports/objective_scores.csv` / `.json` — machine-readable metrics",
        "- `reports/human_scores.csv` — 1–5 review template",
        "- `sheets/by_source/` and `sheets/by_method/` — contact sheets",
    ]
    (reports_root / "benchmark_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_phase_2a(
    context: V2RunContext,
    *,
    output_root: Path = DEFAULT_OUT,
    ai_input_root: Path = AI_INPUT_ROOT,
    force: bool = False,
) -> list[dict[str, Any]]:
    """Run all selected Phase 2A methods after immutable preflight."""

    output_root = output_root.resolve()
    ai_input_root = ai_input_root.resolve()
    _preflight_ai_inputs(context, ai_input_root)
    options = _options(context)
    source_ids = [*context.tier_a_sources, *context.tier_b_sources]
    rows: list[dict[str, Any]] = []
    for method_id in context.methods:
        (output_root / "raw" / method_id).mkdir(parents=True, exist_ok=True)
        (output_root / "post" / method_id).mkdir(parents=True, exist_ok=True)
    for source_id in source_ids:
        source_path = _source_path(context, source_id)
        with Image.open(source_path) as opened:
            source = opened.convert("RGBA")
        for method_id in context.methods:
            raw_path = output_root / "raw" / method_id / f"{source_id}.png"
            post_path = output_root / "post" / method_id / f"{source_id}.png"
            if method_id in ("A1", "A2", "B1"):
                raw = _run_local_method(method_id, source, options)
            else:
                with Image.open(_ai_input_path(ai_input_root, method_id, source_id)) as opened:
                    raw = opened.convert("RGBA")
            if force or not raw_path.exists():
                raw.save(raw_path, format="PNG", optimize=False)
            post = shared_post_process(raw)
            if force or not post_path.exists():
                post.save(post_path, format="PNG", optimize=False)
            for state, image, path in (("raw", raw, raw_path), ("post", post, post_path)):
                rows.append({"source_id": source_id, "method_id": method_id, "method_label": METHOD_LABELS[method_id], "state": state, "path": str(path), **objective_metrics(image)})
    _write_sheets(rows, output_root / "sheets", source_ids, list(context.methods))
    _write_reports(rows, output_root / "reports", context)
    return rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--ai-input-root", type=Path, default=AI_INPUT_ROOT)
    parser.add_argument("--methods", nargs="+", choices=("A1", "A2", "B1", "C1", "C2"), default=None)
    parser.add_argument("--tier-a-sources", nargs="+", default=None)
    parser.add_argument("--tier-b-sources", nargs="+", default=None)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    context = prepare_run(
        config_path=args.config if args.config.is_absolute() else ROOT / args.config,
        output_root=args.out if args.out.is_absolute() else ROOT / args.out,
        methods=args.methods,
        tier_a_sources=args.tier_a_sources,
        tier_b_sources=args.tier_b_sources,
    )
    rows = run_phase_2a(
        context,
        output_root=args.out if args.out.is_absolute() else ROOT / args.out,
        ai_input_root=args.ai_input_root if args.ai_input_root.is_absolute() else ROOT / args.ai_input_root,
        force=args.force,
    )
    print(f"phase2A complete: {len(rows)} raw/post records")
    print(f"summary: {(args.out if args.out.is_absolute() else ROOT / args.out) / 'reports' / 'benchmark_summary.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
