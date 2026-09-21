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
import shutil
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
from studio.static_mode.pixelize.ai_cleanup import AiPixelMasterCleanupOptions, ai_pixel_master_cleanup
from studio.static_mode.pixelize.logical_grid import validate_and_unzoom
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


def _provenance_path(image_path: Path) -> Path:
    return image_path.with_suffix(".json")


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _load_ai_provenance(
    *,
    ai_root: Path,
    method_id: str,
    source_id: str,
    source_path: Path,
    transport_path: Path,
) -> tuple[dict[str, Any] | None, Path | None, str | None]:
    """Return imported AI provenance or a contract failure reason."""

    manifest_path = _provenance_path(transport_path)
    if not manifest_path.is_file():
        return None, None, "FAIL_PROVENANCE"
    payload = _read_json(manifest_path)
    if payload is None:
        return None, None, "FAIL_PROVENANCE"
    required = ("source_id", "method", "stage", "provider", "model", "prompt_sha256", "source_sha256", "transport_sha256")
    if any(field not in payload or payload[field] in (None, "") for field in required):
        return None, None, "FAIL_PROVENANCE"
    if payload["source_id"] != source_id or payload["method"] != method_id:
        return None, None, "FAIL_PROVENANCE"
    expected_stage = "final-128-logical-transport"
    if payload["stage"] != expected_stage:
        return None, None, "FAIL_PROVENANCE"
    if payload["source_sha256"] != _sha256(source_path) or payload["transport_sha256"] != _sha256(transport_path):
        return None, None, "FAIL_PROVENANCE"

    intermediate_path: Path | None = None
    if method_id == "C2":
        raw_intermediate = payload.get("intermediate_path")
        if raw_intermediate:
            intermediate_path = Path(raw_intermediate)
            if not intermediate_path.is_absolute():
                intermediate_path = manifest_path.parent / intermediate_path
        else:
            intermediate_path = ai_root.parent / "intermediate" / method_id / f"{source_id}.png"
        if not intermediate_path.is_file() or not payload.get("intermediate_sha256"):
            return None, None, "FAIL_PROVENANCE"
        if payload["intermediate_sha256"] != _sha256(intermediate_path):
            return None, None, "FAIL_PROVENANCE"
    return payload, intermediate_path, None


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


def _logical_tile(row: dict[str, Any], size: tuple[int, int] = (560, 560)) -> Image.Image:
    tile = Image.new("RGBA", size, (250, 250, 250, 255))
    path = Path(row["path"]) if row.get("path") else None
    status = str(row.get("status") or "FAIL")
    if path and path.is_file():
        with Image.open(path) as opened:
            logical = opened.convert("RGBA")
        preview = logical.resize((logical.width * 4, logical.height * 4), Image.Resampling.NEAREST)
        x = max(0, (size[0] - preview.width) // 2)
        y = max(0, (size[1] - 36 - preview.height) // 2)
        tile.alpha_composite(preview, (x, y))
    else:
        draw = ImageDraw.Draw(tile)
        draw.rectangle((16, 16, size[0] - 16, size[1] - 48), fill=(255, 232, 232, 255), outline=(180, 40, 40, 255), width=3)
        draw.text((32, size[1] // 2 - 8), status, fill=(150, 20, 20, 255))
    ImageDraw.Draw(tile).text((16, size[1] - 30), f"{row['method_id']} {status}", fill=(20, 20, 24, 255))
    return tile


def _write_sheets(rows: list[dict[str, Any]], sheets_root: Path, source_ids: list[str], method_ids: list[str]) -> None:
    by_source = sheets_root / "by_source"
    by_method = sheets_root / "by_method"
    ai_audit = sheets_root / "ai_audit"
    for folder in (by_source, by_method, ai_audit):
        folder.mkdir(parents=True, exist_ok=True)

    row_map = {(row["source_id"], row["method_id"]): row for row in rows}
    tile_width, tile_height = 560, 560
    for source_id in source_ids:
        tiles = [_logical_tile(row_map[(source_id, method_id)]) for method_id in method_ids]
        columns = 3
        rows_count = max(1, (len(tiles) + columns - 1) // columns)
        sheet = Image.new("RGBA", (columns * tile_width, rows_count * tile_height), (250, 250, 250, 255))
        for index, tile in enumerate(tiles):
            sheet.alpha_composite(tile, ((index % columns) * tile_width, (index // columns) * tile_height))
        sheet.save(by_source / f"{source_id}.png", format="PNG", optimize=False)

    for method_id in method_ids:
        tiles = [_logical_tile(row_map[(source_id, method_id)]) for source_id in source_ids]
        columns = 3
        rows_count = max(1, (len(tiles) + columns - 1) // columns)
        sheet = Image.new("RGBA", (columns * tile_width, rows_count * tile_height), (250, 250, 250, 255))
        for index, tile in enumerate(tiles):
            sheet.alpha_composite(tile, ((index % columns) * tile_width, (index // columns) * tile_height))
        sheet.save(by_method / f"{method_id}.png", format="PNG", optimize=False)

    for method_id in (method_id for method_id in method_ids if method_id in ("C1", "C2")):
        tiles: list[Image.Image] = []
        for source_id in source_ids:
            row = row_map[(source_id, method_id)]
            transport = Path(row["transport_path"]) if row.get("transport_path") else None
            if transport and transport.is_file():
                tiles.append(_tile(transport, f"{method_id} {source_id} transport"))
            intermediate = Path(row["intermediate_path"]) if row.get("intermediate_path") else None
            if intermediate and intermediate.is_file():
                tiles.append(_tile(intermediate, f"{method_id} {source_id} intermediate"))
        columns = 4
        rows_count = max(1, (len(tiles) + columns - 1) // columns)
        sheet = Image.new("RGBA", (columns * 220, rows_count * 260), (250, 250, 250, 255))
        for index, tile in enumerate(tiles):
            sheet.alpha_composite(tile, ((index % columns) * 220, (index // columns) * 260))
        sheet.save(ai_audit / f"{method_id}.png", format="PNG", optimize=False)


def _write_reports(
    rows: list[dict[str, Any]],
    reports_root: Path,
    context: V2RunContext,
    source_ids: list[str],
    method_ids: list[str],
) -> None:
    reports_root.mkdir(parents=True, exist_ok=True)
    (reports_root / "logical_grid_results.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    grid_fields = [
        "source_id", "method_id", "status", "provenance_status", "transport_path", "intermediate_path",
        "logical_path", "logical_grid_pass", "logical_width", "logical_height", "inferred_scale_x",
        "inferred_scale_y", "grid_confidence", "within_cell_variance", "edge_alignment_score",
        "alpha_consistency", "warnings",
    ]
    with (reports_root / "logical_grid_results.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=grid_fields)
        writer.writeheader()
        writer.writerows({field: row.get(field) for field in grid_fields} for row in rows)

    objective_fields = [
        "source_id", "method_id", "status", "path", "width", "height", "palette_size",
        "alpha_fringe_pixels", "isolated_pixel_count", "occupied_bbox_ratio", "target_height_error", "sha256",
    ]
    with (reports_root / "objective_scores.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=objective_fields)
        writer.writeheader()
        writer.writerows({field: row.get(field) for field in objective_fields} for row in rows)

    human_fields = [
        "source_id", "method_id", "identity_fidelity", "silhouette_readability", "face_readability",
        "costume_readability", "asymmetric_feature_preservation", "pixel_cluster_quality", "palette_cleanliness",
        "outline_quality", "cleanup_burden", "production_readiness", "notes",
    ]
    with (reports_root / "human_scores.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=human_fields)
        writer.writeheader()
        for source_id in source_ids:
            for method_id in method_ids:
                writer.writerow({"source_id": source_id, "method_id": method_id})

    valid = [row for row in rows if row.get("status") == "PASS" and row.get("palette_size") is not None]
    means: dict[str, float] = {}
    for method_id in method_ids:
        values = [float(row["palette_size"]) for row in valid if row["method_id"] == method_id]
        if values:
            means[method_id] = round(statistics.mean(values), 3)
    if means:
        best_value = min(means.values())
        tied = [method_id for method_id in method_ids if means.get(method_id) == best_value]
        if len(tied) == 1:
            proxy_line = f"- Objective palette-size proxy: {tied[0]} ({best_value})"
        else:
            proxy_line = f"- Objective palette-size proxy: TIE — {', '.join(tied)} ({best_value})"
    else:
        proxy_line = "- Objective palette-size proxy: unavailable (no valid logical outputs)"

    status_counts: dict[str, int] = {}
    for row in rows:
        status_counts[row["status"]] = status_counts.get(row["status"], 0) + 1
    status_text = ", ".join(f"{key}={value}" for key, value in sorted(status_counts.items()))
    lines = [
        "# Pixel Master Benchmark V2 — Phase 2A Logical Rebenchmark",
        "",
        "## Scope",
        "",
        f"- Sources: {len(source_ids)} ({', '.join(source_ids)})",
        f"- Methods: {len(method_ids)} ({', '.join(method_ids)})",
        "- Compared artifact: validated logical master only",
        "- Preview: 4× nearest-neighbor for every logical tile",
        "",
        "## Execution result",
        "",
        f"- Logical comparisons: {len(source_ids)} sources × {len(method_ids)} methods = {len(rows)} method results",
        f"- Status: {status_text}",
        proxy_line,
        "- Objective palette-size proxy is not a visual-quality decision; no visual ranking is emitted.",
        "- Human review: pending; `human_scores.csv` intentionally remains blank.",
        "",
        "## Artifacts",
        "",
        "- `logical/` — only accepted logical masters",
        "- `transport/` and `intermediate/` — AI audit artifacts only",
        "- `validation/` — logical-grid and provenance records",
        "- `sheets/by_source/` and `sheets/by_method/` — logical-only contact sheets",
        "- `sheets/ai_audit/` — transport/intermediate audit sheets",
        "- `reports/logical_grid_results.csv` — validation and failure records",
    ]
    (reports_root / "smoke_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (reports_root / "benchmark_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_phase_2a(
    context: V2RunContext,
    *,
    output_root: Path = DEFAULT_OUT,
    ai_input_root: Path = AI_INPUT_ROOT,
    force: bool = False,
) -> list[dict[str, Any]]:
    """Run the logical-only Phase 2A benchmark.

    A1/A2/B1 use the deterministic Preserve candidates. C1/C2 are treated as
    imported transport and must pass both provenance and logical-grid gates.
    No failed AI transport is resized or promoted.
    """

    output_root = output_root.resolve()
    ai_input_root = ai_input_root.resolve()
    options = _options(context)
    source_ids = [*context.tier_a_sources, *context.tier_b_sources]
    method_ids = list(context.methods)
    rows: list[dict[str, Any]] = []
    for folder in ("logical", "transport", "intermediate", "validation"):
        for method_id in method_ids:
            (output_root / folder / method_id).mkdir(parents=True, exist_ok=True)
    manifest = {
        "kind": "pixel-master-phase2a-rebench-128logical",
        "version": 1,
        "config": str(context.config_path),
        "sources": source_ids,
        "methods": method_ids,
        "fixture_policy": "immutable-existing-files-only",
        "ai_input_policy": "transport-sidecar-required",
        "logical_preview_scale": 4,
    }
    (output_root / "run_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for source_id in source_ids:
        source_path = _source_path(context, source_id)
        with Image.open(source_path) as opened:
            source = opened.convert("RGBA")
        for method_id in method_ids:
            logical_path = output_root / "logical" / method_id / f"{source_id}.png"
            transport_output = output_root / "transport" / method_id / f"{source_id}.png"
            intermediate_output = output_root / "intermediate" / method_id / f"{source_id}.png"
            validation_path = output_root / "validation" / method_id / f"{source_id}.json"
            row: dict[str, Any] = {
                "source_id": source_id,
                "method_id": method_id,
                "method_label": METHOD_LABELS[method_id],
                "state": "logical",
                "status": "PASS",
                "provenance_status": "not_applicable",
                "path": "",
                "logical_path": "",
                "transport_path": "",
                "intermediate_path": "",
                "logical_grid_pass": None,
                "logical_width": None,
                "logical_height": None,
                "inferred_scale_x": None,
                "inferred_scale_y": None,
                "grid_confidence": None,
                "within_cell_variance": None,
                "edge_alignment_score": None,
                "alpha_consistency": None,
                "warnings": [],
            }
            if method_id in ("A1", "A2", "B1"):
                raw = _run_local_method(method_id, source, options)
                logical = shared_post_process(raw)
                if force or not logical_path.exists():
                    logical.save(logical_path, format="PNG", optimize=False)
                row.update({
                    "path": str(logical_path),
                    "logical_path": str(logical_path),
                    "logical_width": logical.width,
                    "logical_height": logical.height,
                })
                row.update(objective_metrics(logical))
            else:
                input_path = _ai_input_path(ai_input_root, method_id, source_id)
                # A rerun must not leave a prior accepted logical master in
                # place when the new transport fails provenance or grid gates.
                logical_path.unlink(missing_ok=True)
                validation_path.unlink(missing_ok=True)
                row["provenance_status"] = "pending"
                if input_path.is_file():
                    if force or not transport_output.exists():
                        shutil.copyfile(input_path, transport_output)
                    row["transport_path"] = str(transport_output)
                else:
                    row["status"] = "FAIL_PROVENANCE"
                    row["provenance_status"] = "FAIL_PROVENANCE"
                    row["warnings"] = [{"code": "FAIL_PROVENANCE", "message": "AI transport input is missing."}]
                if row["status"] == "PASS":
                    provenance, intermediate_path, provenance_error = _load_ai_provenance(
                        ai_root=ai_input_root,
                        method_id=method_id,
                        source_id=source_id,
                        source_path=source_path,
                        transport_path=input_path,
                    )
                    if provenance_error:
                        row["status"] = provenance_error
                        row["provenance_status"] = provenance_error
                        row["warnings"] = [{"code": provenance_error, "message": "AI transport sidecar is missing or does not match its source/artifact hashes."}]
                    else:
                        row["provenance_status"] = "PASS"
                        if intermediate_path and intermediate_path.is_file():
                            if force or not intermediate_output.exists():
                                shutil.copyfile(intermediate_path, intermediate_output)
                            row["intermediate_path"] = str(intermediate_output)
                        with Image.open(input_path) as opened:
                            transport = opened.convert("RGBA")
                        validation = validate_and_unzoom(transport, alpha_threshold=options.alpha_threshold)
                        validation_payload = validation.to_dict()
                        validation_payload["provenance"] = provenance
                        validation_path.write_text(json.dumps(validation_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                        row.update({
                            "logical_grid_pass": validation.pass_,
                            "logical_width": validation.logical_width,
                            "logical_height": validation.logical_height,
                            "inferred_scale_x": validation.inferred_scale_x,
                            "inferred_scale_y": validation.inferred_scale_y,
                            "grid_confidence": validation.grid_confidence,
                            "within_cell_variance": validation.within_cell_variance,
                            "edge_alignment_score": validation.edge_alignment_score,
                            "alpha_consistency": validation.alpha_consistency,
                            "warnings": list(validation.warnings),
                        })
                        if not validation.pass_ or validation.logical_image is None:
                            row["status"] = "FAIL_LOGICAL_GRID"
                        else:
                            cleaned = ai_pixel_master_cleanup(
                                validation.logical_image,
                                AiPixelMasterCleanupOptions(
                                    target_size=options.target_size,
                                    palette_size=options.palette_size,
                                    alpha_threshold=options.alpha_threshold,
                                    geometry_resize=False,
                                ),
                            )
                            logical = cleaned.image
                            if force or not logical_path.exists():
                                logical.save(logical_path, format="PNG", optimize=False)
                            row["path"] = str(logical_path)
                            row["logical_path"] = str(logical_path)
                            row.update(objective_metrics(logical))
            if method_id in ("C1", "C2") and row["status"] != "PASS" and not validation_path.exists():
                validation_path.write_text(
                    json.dumps(
                        {
                            "pass": False,
                            "status": row["status"],
                            "provenance_status": row["provenance_status"],
                            "warnings": row["warnings"],
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                    + "\n",
                    encoding="utf-8",
                )
            if row["status"] != "PASS":
                row.update({
                    "width": None,
                    "height": None,
                    "palette_size": None,
                    "alpha_fringe_pixels": None,
                    "isolated_pixel_count": None,
                    "occupied_bbox_ratio": None,
                    "target_height_error": None,
                    "sha256": None,
                })
            rows.append(row)
    _write_sheets(rows, output_root / "sheets", source_ids, method_ids)
    _write_reports(rows, output_root / "reports", context, source_ids, method_ids)
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
    print(f"phase2A logical benchmark complete: {len(rows)} method results")
    print(f"summary: {(args.out if args.out.is_absolute() else ROOT / args.out) / 'reports' / 'benchmark_summary.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
