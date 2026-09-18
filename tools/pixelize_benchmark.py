#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Run the Pixelize Phase 1 benchmark and write reproducible artifacts.

Phase 1 is intentionally a small, high-signal experiment:

* A1: the current M1.1 Pixelize pipeline;
* A2: subject geometry first, BOX resize, palette after resize;
* A3: subject geometry first, LANCZOS resize, palette after resize.

The runner is restartable. Each case stores its input hash, configuration
fingerprint, timing, determinism check, palette/alpha metrics, and the result
image. When the requested case already has matching metadata it is skipped
unless ``--force`` is supplied. ``--bootstrap-synthetic`` creates the ten
deterministic proxy inputs described by the Phase 1 plan; they are explicitly
labelled as synthetic so they are not mistaken for the human-source set.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import platform
import shutil
import statistics
import sys
import tempfile
import time
from collections import deque
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from studio.shared.benchmark.metrics import edge_cleanliness, silhouette_accuracy, thin_feature_recovery
from studio.shared.palette import apply_palette, build_palette, opaque_colors, palette_distance_report
from studio.static_mode.pixelize import PixelizeOptions, pixelize_image
from studio.static_mode.pixelize import engine as pixelize_engine


METHODS = ("A1_current_m1_1", "A2_box", "A3_lanczos")
DEFAULT_CONFIG = ROOT / "benchmark" / "configs" / "benchmark_matrix.json"
DEFAULT_OUT = ROOT / "benchmark" / "outputs"
DEFAULT_SHEETS = ROOT / "benchmark" / "sheets"
DEFAULT_REPORT = ROOT / "benchmark" / "reports" / "benchmark_summary.md"


def _json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_json_dump(value), encoding="utf-8")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_name(value: Any) -> str:
    return str(value).replace("/", "-").replace("\\", "-").replace(" ", "_")


def _palette_name(value: Any) -> str:
    return "auto" if value in (None, "auto") else str(int(value))


def _load_config(path: Path) -> dict[str, Any]:
    config = json.loads(path.read_text(encoding="utf-8"))
    if config.get("version") != 1 or config.get("phase") != "phase1":
        raise ValueError(f"unsupported benchmark config: {path}")
    source_entries = config.get("dataset", {}).get("sources", [])
    if len(source_entries) < int(config.get("dataset", {}).get("minimum_sources", 10)):
        raise ValueError("Phase 1 requires at least ten dataset entries")
    method_ids = [item["id"] for item in config.get("methods", [])]
    missing = [item for item in METHODS if item not in method_ids]
    if missing:
        raise ValueError(f"benchmark config is missing methods: {missing}")
    return config


def _rgba_background(size: tuple[int, int], color: tuple[int, int, int, int]) -> Image.Image:
    return Image.new("RGBA", size, color)


def _draw_character(
    image: Image.Image,
    *,
    center: tuple[int, int],
    scale: float = 1.0,
    body: tuple[int, int, int] = (64, 117, 184),
    hair: tuple[int, int, int] = (39, 33, 58),
    skin: tuple[int, int, int] = (245, 190, 157),
    outline: tuple[int, int, int] = (29, 28, 41),
    three_quarter: bool = False,
    detailed: bool = False,
    long_hair: bool = False,
    weapon: bool = False,
) -> None:
    """Draw a compact, deterministic illustration proxy with useful features."""
    d = ImageDraw.Draw(image, "RGBA")
    cx, cy = center
    s = float(scale)

    def box(x0: float, y0: float, x1: float, y1: float) -> tuple[int, int, int, int]:
        return tuple(int(round(v)) for v in (cx + x0 * s, cy + y0 * s, cx + x1 * s, cy + y1 * s))

    def width(value: float) -> int:
        return max(1, int(round(value * s)))

    # Silhouette, head, neck, and body.
    d.ellipse(box(-48, -168, 48, -70), fill=skin + (255,), outline=outline + (255,), width=width(8))
    d.rounded_rectangle(box(-20, -82, 20, -55), radius=width(8), fill=skin + (255,), outline=outline + (255,), width=width(5))
    d.rounded_rectangle(box(-70, -65, 70, 116), radius=width(18), fill=body + (255,), outline=outline + (255,), width=width(9))
    d.polygon([box(-70, 100, -16, 100)[0:2], box(-28, 100, -5, 182)[0:2], box(5, 100, 28, 182)[0:2], box(70, 100, 16, 100)[0:2]], fill=outline + (255,))

    # Hair mass and fringe preserve narrow boundaries at low target sizes.
    d.pieslice(box(-58, -184, 58, -57), 180, 360, fill=hair + (255,), outline=outline + (255,), width=width(7))
    fringe = [box(-55, -135, -27, -69), box(-28, -145, -3, -68), box(-5, -140, 21, -66), box(18, -130, 47, -59)]
    for index, segment in enumerate(fringe):
        if three_quarter and index == 0:
            continue
        d.polygon([(segment[0], segment[1]), (segment[2], segment[1]), (segment[2] - width(8), segment[3]), (segment[0] + width(13), segment[3])], fill=hair + (255,))
    if long_hair:
        d.polygon([box(-47, -105, -26, -105)[0:2], box(-85, 94, -42, 94)[0:2], box(-52, 126, -17, 126)[0:2], box(-12, -92, -17, -92)[0:2]], fill=hair + (255,))
        d.line([box(-48, -100, -48, 105)[0:2], box(-60, -20, -60, 113)[0:2], box(-25, -90, -38, 135)[0:2]], fill=outline + (255,), width=width(6), joint="curve")

    # Face and expression.
    eye_y = -107
    eye_dx = 25 if three_quarter else 23
    d.ellipse(box(-eye_dx - 7, eye_y - 5, -eye_dx + 9, eye_y + 12), fill=outline + (255,))
    d.ellipse(box(eye_dx - 7, eye_y - 5, eye_dx + 9, eye_y + 12), fill=outline + (255,))
    d.ellipse(box(-eye_dx - 2, eye_y - 1, -eye_dx + 4, eye_y + 6), fill=(238, 245, 255, 255))
    if not three_quarter:
        d.ellipse(box(eye_dx - 2, eye_y - 1, eye_dx + 4, eye_y + 6), fill=(238, 245, 255, 255))
    d.line([box(-12, -82, 13, -82)[0:2], box(0, -76, 0, -76)[0:2]], fill=outline + (255,), width=width(4))

    # Arms, belt, seams, and buttons add interior boundaries.
    arm_y = 2
    d.line([box(-57, arm_y, -110, 70)[0:2], box(-110, 70, -114, 112)[0:2]], fill=outline + (255,), width=width(18), joint="curve")
    d.line([box(57, arm_y, 111, 58)[0:2], box(111, 58, 115, 100)[0:2]], fill=outline + (255,), width=width(18), joint="curve")
    d.line([box(-48, 26, 48, 26)[0:2]], fill=(205, 165, 70, 255), width=width(9))
    d.line([box(-49, 59, 49, 59)[0:2]], fill=outline + (255,), width=width(5))
    d.ellipse(box(-11, 17, 11, 39), fill=(228, 194, 77, 255), outline=outline + (255,), width=width(3))
    if detailed:
        for y in (75, 92):
            d.line([box(-38, y, 38, y)[0:2]], fill=(111, 169, 211, 255), width=width(4))
        for x in (-28, 28):
            d.ellipse(box(x - 7, 73, x + 7, 87), fill=(240, 214, 122, 255), outline=outline + (255,), width=width(2))
        d.line([box(-66, -8, -28, 35)[0:2]], fill=(214, 226, 239, 255), width=width(5))
        d.line([box(66, -8, 28, 35)[0:2]], fill=(214, 226, 239, 255), width=width(5))

    if weapon:
        wx = 147 if not three_quarter else 118
        d.line([box(wx, -188, wx, 135)[0:2]], fill=outline + (255,), width=width(10))
        d.line([box(wx, -185, wx, 130)[0:2]], fill=(197, 217, 229, 255), width=width(4))
        d.polygon([box(wx - 17, -188, wx + 17, -188)[0:2], box(wx, -232, wx + 17, -188)[0:2], box(wx - 17, -188, wx, -232)[0:2]], fill=(215, 233, 243, 255), outline=outline + (255,))
        d.line([box(wx - 26, 20, wx + 26, 20)[0:2]], fill=(218, 176, 73, 255), width=width(8))


def _source_image(source_id: str) -> Image.Image:
    size = (512, 512)
    if source_id == "D01":
        image = _rgba_background(size, (0, 0, 0, 0))
        _draw_character(image, center=(256, 255), scale=1.12, body=(69, 125, 192))
    elif source_id == "D02":
        image = _rgba_background(size, (0, 0, 0, 0))
        _draw_character(image, center=(270, 258), scale=1.05, body=(184, 82, 105), three_quarter=True)
    elif source_id == "D03":
        image = _rgba_background(size, (0, 0, 0, 0))
        d = ImageDraw.Draw(image, "RGBA")
        d.ellipse((125, 120, 387, 390), fill=(242, 190, 70, 255), outline=(35, 32, 44, 255), width=14)
        d.polygon([(160, 150), (185, 75), (230, 139), (282, 138), (330, 75), (352, 158)], fill=(61, 49, 85, 255), outline=(35, 32, 44, 255))
        d.ellipse((188, 230, 224, 266), fill=(35, 32, 44, 255)); d.ellipse((287, 230, 323, 266), fill=(35, 32, 44, 255))
        d.line((220, 320, 292, 320), fill=(35, 32, 44, 255), width=10)
        d.rectangle((183, 369, 329, 430), fill=(58, 143, 151, 255), outline=(35, 32, 44, 255), width=10)
    elif source_id == "D04":
        image = _rgba_background(size, (0, 0, 0, 0))
        _draw_character(image, center=(254, 255), scale=1.08, body=(76, 118, 151), hair=(50, 35, 55), detailed=True)
    elif source_id == "D05":
        image = _rgba_background(size, (0, 0, 0, 0))
        _draw_character(image, center=(250, 252), scale=1.08, body=(102, 79, 170), hair=(57, 35, 92), long_hair=True)
    elif source_id == "D06":
        image = _rgba_background(size, (0, 0, 0, 0))
        _draw_character(image, center=(229, 260), scale=0.98, body=(69, 142, 104), weapon=True)
    elif source_id == "D07":
        image = _rgba_background(size, (0, 0, 0, 0))
        _draw_character(image, center=(258, 258), scale=1.0, body=(190, 91, 70), detailed=True)
        d = ImageDraw.Draw(image, "RGBA")
        d.ellipse((386, 118, 455, 187), fill=(110, 215, 227, 120), outline=(226, 249, 255, 180), width=5)
        d.line((398, 202, 451, 257), fill=(226, 249, 255, 140), width=4)
    elif source_id == "D08":
        image = _rgba_background(size, (226, 218, 195, 255))
        d = ImageDraw.Draw(image, "RGBA")
        d.rectangle((18, 18, 493, 493), outline=(181, 168, 143, 255), width=8)
        _draw_character(image, center=(257, 257), scale=1.05, body=(54, 115, 175), detailed=True)
    elif source_id == "D09":
        image = _rgba_background(size, (0, 0, 0, 0))
        _draw_character(image, center=(188, 267), scale=0.76, body=(66, 137, 183))
        _draw_character(image, center=(370, 291), scale=0.52, body=(178, 84, 100), hair=(78, 40, 49), three_quarter=True)
    elif source_id == "D10":
        image = _rgba_background(size, (0, 0, 0, 0))
        _draw_character(image, center=(257, 258), scale=1.03, body=(127, 139, 158), hair=(86, 83, 111), skin=(210, 176, 160), detailed=True)
        d = ImageDraw.Draw(image, "RGBA")
        for i in range(12):
            x = 75 + ((i * 71) % 365)
            y = 55 + ((i * 97) % 390)
            d.ellipse((x, y, x + 22, y + 22), fill=(150, 161, 173, 45))
    else:
        raise KeyError(source_id)
    return image


def bootstrap_synthetic_sources(config: dict[str, Any], *, force: bool = False) -> list[Path]:
    root = ROOT / config["dataset"]["source_root"]
    root.mkdir(parents=True, exist_ok=True)
    created: list[Path] = []
    for entry in config["dataset"]["sources"]:
        path = root / entry["file"]
        if path.exists() and not force:
            continue
        image = _source_image(entry["id"])
        image.save(path, format="PNG", optimize=False)
        created.append(path)
    return created


def _options(matrix: dict[str, Any], size: int, palette_size: Any, detail: str) -> PixelizeOptions:
    return PixelizeOptions(
        target_size=int(size),
        palette_size=None if palette_size in (None, "auto") else int(palette_size),
        dither=str(matrix["dither"]),
        background=str(matrix["background"]),
        outline=str(matrix["outline"]),
        alpha_threshold=int(matrix["alpha_threshold"]),
        subject_mode="auto",
        detail=str(detail),
    )


def _prepare_subject(source: Image.Image, options: PixelizeOptions) -> tuple[Image.Image, tuple[int, int, int, int], list[dict[str, Any]], list[dict[str, Any]]]:
    normalized, normalise_warnings = pixelize_engine._normalise_alpha(source, options)
    subject, bbox, candidates, select_warnings = pixelize_engine._subject_selection(normalized, options)
    return subject, bbox, candidates, [*normalise_warnings, *select_warnings]


def _run_method(method_id: str, source: Image.Image, options: PixelizeOptions) -> tuple[Image.Image, tuple[tuple[int, int, int, int], ...], dict[str, Any], Image.Image, tuple[int, int, int, int], list[dict[str, Any]]]:
    if method_id == "A1_current_m1_1":
        logical, palette, report = pixelize_image(source, options)
        subject, bbox, candidates, warnings = _prepare_subject(source, options)
        return logical, palette, report, subject, bbox, candidates
    subject, bbox, candidates, warnings = _prepare_subject(source, options)
    logical_size = pixelize_engine._logical_size(subject.size, options.target_size)
    resample_name = "BOX" if method_id == "A2_box" else "LANCZOS"
    resampling = Image.Resampling.BOX if resample_name == "BOX" else Image.Resampling.LANCZOS
    resized = subject.resize(logical_size, resampling)
    palette_size = options.palette_size or pixelize_engine._auto_palette_size(resized, options.alpha_threshold, options.detail)
    palette = build_palette([resized], palette_size, alpha_threshold=options.alpha_threshold, iterations=6)
    logical = apply_palette(resized, palette, alpha_threshold=options.alpha_threshold)
    report = {
        "kind": "sprite-studio-pixelize-benchmark",
        "version": 1,
        "source_size": list(source.size),
        "subject_size": list(subject.size),
        "subject_bbox": list(bbox),
        "subject_candidates": candidates,
        "logical_size": list(logical.size),
        "profile": {
            **asdict(options),
            "subject_bbox": list(bbox),
            "palette_mode": "auto" if options.palette_size is None else "fixed",
            "resolved_palette_size": len(palette),
            "palette_scope": "resized-subject",
            "operation_order": f"normalize -> subject -> resize:{resample_name} -> palette -> remap",
            "alpha_mode": "binary",
        },
        "palette": {"requested": palette_size, "colors": len(palette), "entries": [list(entry) for entry in palette], "separation": palette_distance_report(palette)},
        "warnings": warnings,
    }
    return logical, palette, report, subject, bbox, candidates


def _tiny_color_islands(image: Image.Image, threshold: int = 128) -> dict[str, Any]:
    array = np.asarray(image.convert("RGBA"), dtype=np.uint8)
    opaque = array[:, :, 3] >= threshold
    height, width = opaque.shape
    visited = np.zeros_like(opaque, dtype=bool)
    tiny = 0
    components = 0
    for y in range(height):
        for x in range(width):
            if not opaque[y, x] or visited[y, x]:
                continue
            components += 1
            color = array[y, x, :3].copy()
            queue: deque[tuple[int, int]] = deque([(x, y)])
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
    total = int(opaque.sum())
    return {"components": components, "tiny_pixels": tiny, "tiny_ratio": round(tiny / total, 6) if total else 0.0}


def _case_metrics(subject: Image.Image, logical: Image.Image, options: PixelizeOptions, palette: tuple[tuple[int, int, int, int], ...], elapsed_ms: float, repeat_hash: str, result_hash: str) -> dict[str, Any]:
    reference = subject.resize(logical.size, Image.Resampling.NEAREST)
    silhouette = silhouette_accuracy(reference, logical)
    thin = thin_feature_recovery(reference, logical)
    alpha = edge_cleanliness(logical)
    islands = _tiny_color_islands(logical, options.alpha_threshold)
    colors, _ = opaque_colors([logical], alpha_threshold=options.alpha_threshold)
    requested = options.palette_size
    palette_compliant = requested is None or int(colors.shape[0]) <= int(requested)
    thin_score = thin.get("recovered")
    if thin_score is None:
        thin_score = 1.0
    fragmentation_score = max(0.0, 1.0 - min(1.0, float(islands["tiny_ratio"]) * 20.0))
    score = 100.0 * (
        0.45 * float(silhouette["iou"])
        + 0.25 * float(thin_score)
        + 0.15 * fragmentation_score
        + 0.10 * (1.0 if alpha["clean"] else 0.0)
        + 0.05 * (1.0 if palette_compliant else 0.0)
    )
    return {
        "runtime_ms": round(float(elapsed_ms), 3),
        "determinism": {"pass": result_hash == repeat_hash, "result_sha256": result_hash, "repeat_sha256": repeat_hash},
        "palette": {"requested": "auto" if requested is None else int(requested), "actual": int(colors.shape[0]), "compliant": bool(palette_compliant)},
        "alpha": {"soft_pixels": int(alpha["soft_alpha_pixels"]), "binary": bool(alpha["clean"])},
        "silhouette": silhouette,
        "thin_feature": thin,
        "color_fragmentation": islands,
        "heuristic_score": round(score, 3),
    }


def _case_key(source_id: str, method_id: str, size: int, palette_size: Any, detail: str) -> str:
    return f"{source_id}/{method_id}/size-{size}_palette-{_palette_name(palette_size)}_detail-{_safe_name(detail)}"


def _write_case_artifacts(artifact_dir: Path, logical: Image.Image, palette: tuple[tuple[int, int, int, int], ...], report: dict[str, Any], subject: Image.Image, matrix: dict[str, Any]) -> dict[str, str]:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    result_path = artifact_dir / "result.png"
    logical.save(result_path, format="PNG", optimize=False)
    preview_paths: dict[str, str] = {}
    for scale in matrix["preview_scales"]:
        preview = logical.resize((logical.width * int(scale), logical.height * int(scale)), Image.Resampling.NEAREST)
        preview_path = artifact_dir / f"preview-{int(scale)}x.png"
        preview.save(preview_path, format="PNG", optimize=False)
        preview_paths[str(scale)] = preview_path.name
    subject_path = artifact_dir / "subject.png"
    subject.save(subject_path, format="PNG", optimize=False)
    _write_json(artifact_dir / "palette.json", {"entries": [list(entry) for entry in palette], "separation": palette_distance_report(palette)})
    _write_json(artifact_dir / "pixelize-report.json", report)
    return {"result": result_path.name, "subject": subject_path.name, "previews": preview_paths}


def _run_case(config: dict[str, Any], source_entry: dict[str, Any], method_id: str, size: int, palette_size: Any, detail: str, out_root: Path, force: bool) -> dict[str, Any]:
    matrix = config["matrix"]
    source_path = ROOT / config["dataset"]["source_root"] / source_entry["file"]
    if not source_path.is_file():
        raise FileNotFoundError(f"missing benchmark source: {source_path}; pass --bootstrap-synthetic or add the Phase 1 source set")
    options = _options(matrix, size, palette_size, detail)
    source_hash = _sha256_file(source_path)
    params = {"source": source_entry["id"], "source_hash": source_hash, "method": method_id, "size": size, "palette_size": palette_size, "detail": detail, "matrix": matrix}
    fingerprint = _sha256_bytes(json.dumps(params, sort_keys=True).encode("utf-8"))
    artifact_dir = out_root / _case_key(source_entry["id"], method_id, size, palette_size, detail)
    metadata_path = artifact_dir / "metadata.json"
    if metadata_path.is_file() and not force:
        try:
            cached = json.loads(metadata_path.read_text(encoding="utf-8"))
            if cached.get("fingerprint") == fingerprint and (artifact_dir / "result.png").is_file():
                return cached["row"]
        except (OSError, json.JSONDecodeError, KeyError):
            pass

    with Image.open(source_path) as opened:
        source = opened.convert("RGBA")
    start = time.perf_counter()
    logical, palette, report, subject, bbox, candidates = _run_method(method_id, source, options)
    elapsed_ms = (time.perf_counter() - start) * 1000.0
    with Image.open(source_path) as opened:
        repeat_source = opened.convert("RGBA")
    repeat_logical, _, _, _, _, _ = _run_method(method_id, repeat_source, options)
    artifact_files = _write_case_artifacts(artifact_dir, logical, palette, report, subject, matrix)
    result_hash = _sha256_file(artifact_dir / "result.png")
    repeat_buffer = tempfile.NamedTemporaryFile(prefix="pixelize-repeat-", suffix=".png", delete=False)
    repeat_path = Path(repeat_buffer.name)
    repeat_buffer.close()
    try:
        repeat_logical.save(repeat_path, format="PNG", optimize=False)
        repeat_hash = _sha256_file(repeat_path)
    finally:
        repeat_path.unlink(missing_ok=True)
    metrics = _case_metrics(subject, logical, options, palette, elapsed_ms, repeat_hash, result_hash)
    row = {
        "source_id": source_entry["id"],
        "source_label": source_entry["label"],
        "method_id": method_id,
        "method_label": next(item["label"] for item in config["methods"] if item["id"] == method_id),
        "size": int(size),
        "palette_size": _palette_name(palette_size),
        "detail": detail,
        "source_path": str(source_path.relative_to(ROOT)).replace("\\", "/"),
        "artifact_dir": str(artifact_dir.relative_to(ROOT)).replace("\\", "/"),
        "result_path": str((artifact_dir / artifact_files["result"]).relative_to(ROOT)).replace("\\", "/"),
        "subject_bbox": list(bbox),
        "subject_candidates": candidates,
        "metrics": metrics,
    }
    report["benchmark"] = {"method_id": method_id, "fingerprint": fingerprint, "metrics": metrics}
    _write_json(artifact_dir / "pixelize-report.json", report)
    _write_json(metadata_path, {"fingerprint": fingerprint, "parameters": params, "row": row})
    return row


def _cases(config: dict[str, Any], source_ids: set[str] | None, method_ids: set[str], sizes: set[int] | None) -> Iterable[tuple[dict[str, Any], str, int, Any, str]]:
    matrix = config["matrix"]
    entries = [entry for entry in config["dataset"]["sources"] if source_ids is None or entry["id"] in source_ids]
    methods = [item["id"] for item in config["methods"] if item["id"] in method_ids]
    combos: list[tuple[int, Any, str]] = []
    for size in matrix["sizes"]:
        for palette_size in matrix["palette_sizes"]:
            for detail in matrix["details"]:
                combos.append((int(size), palette_size, detail))
    combos.extend((int(item["size"]), item["palette_size"], item["detail"]) for item in matrix.get("extra_details", []))
    seen: set[tuple[int, str, str]] = set()
    for size, palette_size, detail in combos:
        if sizes is not None and size not in sizes:
            continue
        key = (size, _palette_name(palette_size), detail)
        if key in seen:
            continue
        seen.add(key)
        for entry in entries:
            for method_id in methods:
                yield entry, method_id, size, palette_size, detail


def _checkerboard(size: tuple[int, int], cell: int = 16) -> Image.Image:
    image = Image.new("RGBA", size, (236, 236, 236, 255))
    d = ImageDraw.Draw(image)
    for y in range(0, size[1], cell):
        for x in range(0, size[0], cell):
            if ((x // cell) + (y // cell)) % 2:
                d.rectangle((x, y, min(size[0] - 1, x + cell - 1), min(size[1] - 1, y + cell - 1)), fill=(205, 205, 205, 255))
    return image


def _preview_tile(path: Path, label: str, dimensions: tuple[int, int] = (300, 330)) -> Image.Image:
    tile = _checkerboard(dimensions)
    d = ImageDraw.Draw(tile)
    try:
        font = ImageFont.load_default()
    except Exception:
        font = None
    with Image.open(path) as opened:
        image = opened.convert("RGBA")
    contained = ImageOps.contain(image, (dimensions[0] - 24, dimensions[1] - 56), method=Image.Resampling.NEAREST)
    x = (dimensions[0] - contained.width) // 2
    y = 10 + (dimensions[1] - 50 - contained.height) // 2
    tile.alpha_composite(contained, (x, y))
    d.text((10, dimensions[1] - 38), label, fill=(24, 24, 28, 255), font=font)
    return tile


def _write_sheets(config: dict[str, Any], rows: list[dict[str, Any]], sheets_root: Path) -> None:
    focus = config["matrix"]["focus"]
    focus_rows = [row for row in rows if row["size"] == int(focus["size"]) and row["palette_size"] == _palette_name(focus["palette_size"]) and row["detail"] == focus["detail"]]
    sheets_root.mkdir(parents=True, exist_ok=True)
    by_source = sheets_root / "by_source"
    by_method = sheets_root / "by_method"
    by_source.mkdir(parents=True, exist_ok=True)
    by_method.mkdir(parents=True, exist_ok=True)
    source_by_id = {entry["id"]: entry for entry in config["dataset"]["sources"]}
    method_order = [item["id"] for item in config["methods"]]
    for source_id, source_entry in source_by_id.items():
        source_path = ROOT / config["dataset"]["source_root"] / source_entry["file"]
        source_rows = {row["method_id"]: row for row in focus_rows if row["source_id"] == source_id}
        tiles = [_preview_tile(source_path, f"{source_id} source")]
        for method_id in method_order:
            row = source_rows.get(method_id)
            if row:
                tiles.append(_preview_tile(ROOT / row["result_path"], f"{method_id} {row['metrics']['heuristic_score']:.1f}"))
        while len(tiles) < 4:
            tiles.append(_preview_tile(source_path, "missing"))
        sheet = Image.new("RGBA", (600, 660), (250, 250, 250, 255))
        for index, tile in enumerate(tiles[:4]):
            sheet.alpha_composite(tile, ((index % 2) * 300, (index // 2) * 330))
        sheet.save(by_source / f"{source_id}_focus.png", format="PNG", optimize=False)
    for method_id in method_order:
        method_rows = {row["source_id"]: row for row in focus_rows if row["method_id"] == method_id}
        tiles = []
        for source_id, source_entry in source_by_id.items():
            row = method_rows.get(source_id)
            if row:
                tiles.append(_preview_tile(ROOT / row["result_path"], f"{source_id} {row['metrics']['heuristic_score']:.1f}", (220, 250)))
        columns = 5
        rows_count = max(1, (len(tiles) + columns - 1) // columns)
        sheet = Image.new("RGBA", (columns * 220, rows_count * 250), (250, 250, 250, 255))
        for index, tile in enumerate(tiles):
            sheet.alpha_composite(tile, ((index % columns) * 220, (index // columns) * 250))
        sheet.save(by_method / f"{method_id}_focus.png", format="PNG", optimize=False)


def _mean(rows: list[dict[str, Any]], path: tuple[str, ...]) -> float | None:
    values: list[float] = []
    for row in rows:
        value: Any = row
        for key in path:
            value = value.get(key) if isinstance(value, dict) else None
        if isinstance(value, (int, float)):
            values.append(float(value))
    return round(statistics.mean(values), 3) if values else None


def _focus_aggregate(config: dict[str, Any], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    focus = config["matrix"]["focus"]
    focus_rows = [row for row in rows if row["size"] == int(focus["size"]) and row["palette_size"] == _palette_name(focus["palette_size"]) and row["detail"] == focus["detail"]]
    aggregates = []
    for method in config["methods"]:
        method_rows = [row for row in focus_rows if row["method_id"] == method["id"]]
        aggregates.append({
            "method_id": method["id"],
            "method_label": method["label"],
            "cases": len(method_rows),
            "mean_heuristic_score": _mean(method_rows, ("metrics", "heuristic_score")),
            "mean_runtime_ms": _mean(method_rows, ("metrics", "runtime_ms")),
            "mean_silhouette_iou": _mean(method_rows, ("metrics", "silhouette", "iou")),
            "mean_thin_recovery": _mean(method_rows, ("metrics", "thin_feature", "recovered")),
            "mean_tiny_color_ratio": _mean(method_rows, ("metrics", "color_fragmentation", "tiny_ratio")),
            "determinism_pass_rate": round(sum(bool(row["metrics"]["determinism"]["pass"]) for row in method_rows) / len(method_rows), 3) if method_rows else None,
            "palette_violations": sum(not bool(row["metrics"]["palette"]["compliant"]) for row in method_rows),
        })
    return aggregates


def _write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _ensure_human_template(report_root: Path, config: dict[str, Any]) -> Path:
    path = report_root / "human_scores_template.csv"
    fields = ["source_id", "method_id", "config", "face_readability", "silhouette_readability", "interior_detail", "outline_quality", "pixel_art_plausibility", "style_faithfulness", "production_usefulness", "notes"]
    rows = []
    focus = config["matrix"]["focus"]
    for source in config["dataset"]["sources"]:
        for method in config["methods"]:
            rows.append({"source_id": source["id"], "method_id": method["id"], "config": f"size-{focus['size']}/palette-{_palette_name(focus['palette_size'])}/detail-{focus['detail']}"})
    _write_csv(path, rows, fields)
    active = report_root / "human_scores.csv"
    if not active.exists():
        shutil.copyfile(path, active)
    return active


def _human_summary(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"status": "missing", "rows": 0}
    fields = ["face_readability", "silhouette_readability", "interior_detail", "outline_quality", "pixel_art_plausibility", "style_faithfulness", "production_usefulness"]
    values: dict[str, list[float]] = {field: [] for field in fields}
    rows = 0
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            numeric = False
            for field in fields:
                try:
                    value = float(row.get(field, ""))
                except (TypeError, ValueError):
                    continue
                if 1 <= value <= 5:
                    values[field].append(value)
                    numeric = True
            if numeric:
                rows += 1
    return {"status": "complete" if rows else "pending", "rows": rows, "means": {key: round(statistics.mean(value), 3) for key, value in values.items() if value}}


def _write_report(config: dict[str, Any], rows: list[dict[str, Any]], report_path: Path, report_root: Path, config_path: Path) -> None:
    report_root.mkdir(parents=True, exist_ok=True)
    aggregates = _focus_aggregate(config, rows)
    _write_json(report_root / "benchmark_results.json", {"kind": "pixelize-phase1-benchmark", "version": 1, "config": str(config_path.relative_to(ROOT)).replace("\\", "/"), "rows": rows, "focus_aggregate": aggregates})
    csv_rows = []
    for row in rows:
        metrics = row["metrics"]
        csv_rows.append({
            "source_id": row["source_id"], "method_id": row["method_id"], "size": row["size"], "palette_size": row["palette_size"], "detail": row["detail"],
            "runtime_ms": metrics["runtime_ms"], "heuristic_score": metrics["heuristic_score"], "deterministic": metrics["determinism"]["pass"], "palette_actual": metrics["palette"]["actual"], "palette_compliant": metrics["palette"]["compliant"],
            "silhouette_iou": metrics["silhouette"]["iou"], "thin_recovery": metrics["thin_feature"].get("recovered"), "tiny_color_ratio": metrics["color_fragmentation"]["tiny_ratio"],
        })
    _write_csv(report_root / "benchmark_scores.csv", csv_rows, list(csv_rows[0].keys()) if csv_rows else ["source_id"])
    human_path = _ensure_human_template(report_root, config)
    human = _human_summary(human_path)
    commit = "unknown"
    try:
        import subprocess
        commit = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:
        pass
    now = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    _write_json(report_root / "run_manifest.json", {
        "kind": "pixelize-phase1-run-manifest",
        "version": 1,
        "generated_at": now,
        "repository_revision": commit,
        "config": str(config_path.relative_to(ROOT)).replace("\\", "/"),
        "case_count": len(rows),
        "determinism_failures": sum(not bool(row["metrics"]["determinism"]["pass"]) for row in rows),
        "python": sys.version,
        "platform": platform.platform(),
        "pillow": getattr(Image, "__version__", "unknown"),
        "numpy": np.__version__,
    })
    focus = config["matrix"]["focus"]
    focus_rows = [row for row in rows if row["size"] == int(focus["size"]) and row["palette_size"] == _palette_name(focus["palette_size"]) and row["detail"] == focus["detail"]]
    winner = max((item for item in aggregates if item["cases"]), key=lambda item: (item["mean_heuristic_score"] or -1, -(item["mean_runtime_ms"] or 1e9)), default=None)
    lines = [
        "# Pixelize Phase 1 Benchmark Summary",
        "",
        f"- Generated: `{now}`",
        f"- Repository revision: `{commit}`",
        f"- Config: `{config_path.relative_to(ROOT).as_posix()}`",
        f"- Dataset: `{config['dataset']['kind']}` with `{len(config['dataset']['sources'])}` deterministic synthetic proxy sources (D01–D10)",
        "- Scope: A1 current M1.1, A2 geometry-first + BOX, A3 geometry-first + LANCZOS",
        "",
        "## Executive result",
        "",
    ]
    if winner:
        lines.append(f"At the focus configuration (`size={focus['size']}`, `palette={_palette_name(focus['palette_size'])}`, `detail={focus['detail']}`), the objective proxy winner is **{winner['method_label']}** with a mean heuristic score of **{winner['mean_heuristic_score']:.3f}/100** across {winner['cases']} sources.")
    else:
        lines.append("No completed focus cases were found.")
    lines.extend([
        "",
        "This is an engineering screening result, not a replacement for the Phase 1 human rubric. The heuristic combines silhouette IoU, thin-feature recovery, fragmentation, binary alpha, and palette compliance; it does not claim face readability or style faithfulness.",
        "",
        "## Focus comparison",
        "",
        "| Method | Cases | Heuristic /100 | Runtime ms | Silhouette IoU | Thin recovery | Tiny-color ratio | Determinism | Palette violations |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for item in aggregates:
        lines.append(f"| {item['method_label']} | {item['cases']} | {item['mean_heuristic_score'] if item['mean_heuristic_score'] is not None else '—'} | {item['mean_runtime_ms'] if item['mean_runtime_ms'] is not None else '—'} | {item['mean_silhouette_iou'] if item['mean_silhouette_iou'] is not None else '—'} | {item['mean_thin_recovery'] if item['mean_thin_recovery'] is not None else '—'} | {item['mean_tiny_color_ratio'] if item['mean_tiny_color_ratio'] is not None else '—'} | {item['determinism_pass_rate'] if item['determinism_pass_rate'] is not None else '—'} | {item['palette_violations']} |")
    lines.extend(["", "## Per-source focus winners", "", "| Source | Winner by heuristic | Score | A1 | A2 | A3 |", "|---|---|---:|---:|---:|---:|"])
    for source in config["dataset"]["sources"]:
        source_rows = [row for row in focus_rows if row["source_id"] == source["id"]]
        scores = {row["method_id"]: row["metrics"]["heuristic_score"] for row in source_rows}
        best = max(source_rows, key=lambda row: row["metrics"]["heuristic_score"], default=None)
        lines.append(f"| {source['id']} {source['label']} | {best['method_label'] if best else '—'} | {best['metrics']['heuristic_score'] if best else '—'} | {scores.get('A1_current_m1_1', '—')} | {scores.get('A2_box', '—')} | {scores.get('A3_lanczos', '—')} |")
    lines.extend([
        "",
        "## Findings and decision",
        "",
        f"- The full matrix contains `{len(rows)}` completed case records (three sizes, Auto/32/48 palettes, Balanced detail, plus Clean and Detailed at 128/Auto).",
        "- Every case records an exact PNG SHA-256 repeat check. A failed determinism check is a hard follow-up item before promoting a candidate.",
        "- The synthetic set intentionally covers transparent sources, opaque-background cleanup, multiple subjects, narrow accessories, long hair, weapons, and low-contrast interiors. It is useful for operation-order screening but cannot validate production style faithfulness.",
        f"- Human review status: **{human['status']}** (`{human['rows']}` scored rows). Fill `benchmark/reports/human_scores.csv` using the 1–5 rubric before making a final visual-quality promotion decision.",
        "",
        "### Recommended next move",
        "",
        f"Keep A1 as the production baseline while using **{winner['method_label'] if winner else 'A2/A3'}** as the Phase 2 comparison candidate. Next add one stronger palette-after-geometry candidate (DPID/PIA-like or a controlled perceptual variant), then rerun this same matrix and the human sheet. Do not delete or silently replace the existing M1.1 route based on the proxy score alone.",
        "",
        "## Artifacts",
        "",
        "- [`benchmark_results.json`](benchmark_results.json) — machine-readable full result set and aggregates",
        "- [`benchmark_scores.csv`](benchmark_scores.csv) — flat metric table",
        "- [`human_scores.csv`](human_scores.csv) — fillable human-review sheet",
        "- [`human_scores_template.csv`](human_scores_template.csv) — blank rubric template",
        "- [`../sheets/by_source`](../sheets/by_source) — per-source A1/A2/A3 focus sheets",
        "- [`../sheets/by_method`](../sheets/by_method) — per-method source overview sheets",
        "",
        "## Reproduction",
        "",
        "```powershell",
        "python tools/pixelize_benchmark.py --bootstrap-synthetic --force",
        "python tools/pixelize_benchmark.py  # restartable; matching cases are skipped",
        "```",
        "",
        "Phase 1 deliberately excludes external image generation, human-score fabrication, and app/UI redesign. Those belong to later phases or manual review.",
    ])
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--sheets", type=Path, default=DEFAULT_SHEETS)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--bootstrap-synthetic", action="store_true", help="create missing deterministic D01-D10 proxy sources")
    parser.add_argument("--force", action="store_true", help="rerun matching cases instead of using cached artifacts")
    parser.add_argument("--no-sheets", action="store_true", help="skip contact-sheet generation")
    parser.add_argument("--methods", nargs="+", choices=METHODS, default=list(METHODS))
    parser.add_argument("--sizes", nargs="+", type=int, default=None)
    parser.add_argument("--sources", nargs="+", default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config_path = args.config if args.config.is_absolute() else ROOT / args.config
    config = _load_config(config_path)
    if args.bootstrap_synthetic:
        created = bootstrap_synthetic_sources(config, force=args.force)
        print(f"bootstrap: {len(created)} source(s) written")
    out_root = args.out if args.out.is_absolute() else ROOT / args.out
    sheets_root = args.sheets if args.sheets.is_absolute() else ROOT / args.sheets
    report_path = args.report if args.report.is_absolute() else ROOT / args.report
    source_ids = set(args.sources) if args.sources else None
    method_ids = set(args.methods)
    rows: list[dict[str, Any]] = []
    total = sum(1 for _ in _cases(config, source_ids, method_ids, set(args.sizes) if args.sizes else None))
    print(f"phase1: {total} case(s)")
    for index, (entry, method_id, size, palette_size, detail) in enumerate(_cases(config, source_ids, method_ids, set(args.sizes) if args.sizes else None), start=1):
        row = _run_case(config, entry, method_id, size, palette_size, detail, out_root, args.force)
        rows.append(row)
        print(f"[{index:03d}/{total:03d}] {row['source_id']} {method_id} size={size} palette={row['palette_size']} detail={detail} score={row['metrics']['heuristic_score']}")
    if not rows:
        raise SystemExit("no cases selected")
    if not args.no_sheets:
        _write_sheets(config, rows, sheets_root)
    _write_report(config, rows, report_path, report_path.parent, config_path)
    print(f"report: {report_path}")
    print(f"artifacts: {out_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
