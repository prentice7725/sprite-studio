#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Execute the Phase 2B semantic-redraw plus PSE benchmark."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from studio.static_mode.pixelize.d1_d2 import (  # noqa: E402
    SemanticPseOptions,
    d1_semantic_pse_file,
    d2_semantic_pse_file,
)
from studio.static_mode.pixelize.structure_extractor import PSE_VERSION  # noqa: E402
from tools.pixel_master_benchmark_v2 import V2RunContext, prepare_run  # noqa: E402
from tools.pixel_master_benchmark_v2_execute import (  # noqa: E402
    _options,
    _run_local_method,
    _source_path,
    objective_metrics,
    shared_post_process,
)


METHODS = ("A1", "A2", "B1", "D1", "D2")
METHOD_LABELS = {
    "A1": "A1 deterministic M1.1",
    "A2": "A2 BOX geometry-first",
    "B1": "B1 deterministic DPID/PIA-like",
    "D1": "D1 semantic redraw + PSE",
    "D2": "D2 two-pass semantic redraw + PSE",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _checkerboard(size: tuple[int, int], cell: int = 16) -> Image.Image:
    image = Image.new("RGBA", size, (238, 238, 238, 255))
    draw = ImageDraw.Draw(image)
    for y in range(0, size[1], cell):
        for x in range(0, size[0], cell):
            if ((x // cell) + (y // cell)) % 2:
                draw.rectangle((x, y, min(size[0] - 1, x + cell - 1), min(size[1] - 1, y + cell - 1)), fill=(208, 208, 208, 255))
    return image


def _logical_tile(row: dict[str, Any], size: tuple[int, int] = (560, 560)) -> Image.Image:
    tile = _checkerboard(size)
    path = Path(row["logical_path"]) if row.get("logical_path") else None
    status = str(row.get("status", "FAIL"))
    if path and path.is_file():
        with Image.open(path) as opened:
            logical = opened.convert("RGBA")
        preview = logical.resize((logical.width * 4, logical.height * 4), Image.Resampling.NEAREST)
        contained = ImageOps.contain(preview, (size[0] - 16, size[1] - 48), method=Image.Resampling.NEAREST)
        tile.alpha_composite(contained, ((size[0] - contained.width) // 2, 8))
    else:
        draw = ImageDraw.Draw(tile)
        draw.rectangle((16, 16, size[0] - 16, size[1] - 48), fill=(255, 232, 232, 255), outline=(180, 40, 40, 255), width=3)
        draw.text((32, size[1] // 2 - 8), status, fill=(150, 20, 20, 255))
    ImageDraw.Draw(tile).text((16, size[1] - 30), f"{row['method_id']} {status}", fill=(20, 20, 24, 255))
    return tile


def _audit_tile(path: Path, label: str, size: tuple[int, int] = (220, 260)) -> Image.Image:
    tile = _checkerboard(size)
    with Image.open(path) as opened:
        image = opened.convert("RGBA")
    contained = ImageOps.contain(image, (size[0] - 16, size[1] - 38), method=Image.Resampling.NEAREST)
    tile.alpha_composite(contained, ((size[0] - contained.width) // 2, 8))
    ImageDraw.Draw(tile).text((8, size[1] - 24), label, fill=(20, 20, 24, 255))
    return tile


def _write_sheets(rows: list[dict[str, Any]], sheets_root: Path, source_ids: list[str]) -> None:
    by_source = sheets_root / "by_source"
    by_method = sheets_root / "by_method"
    semantic_audit = sheets_root / "semantic_audit"
    for folder in (by_source, by_method, semantic_audit):
        folder.mkdir(parents=True, exist_ok=True)
    row_map = {(row["source_id"], row["method_id"]): row for row in rows}
    tile_width, tile_height = 560, 560
    for source_id in source_ids:
        tiles = [_logical_tile(row_map[(source_id, method_id)]) for method_id in METHODS]
        sheet = Image.new("RGBA", (3 * tile_width, 2 * tile_height), (250, 250, 250, 255))
        for index, tile in enumerate(tiles):
            sheet.alpha_composite(tile, ((index % 3) * tile_width, (index // 3) * tile_height))
        sheet.save(by_source / f"{source_id}.png", format="PNG", optimize=False)
    for method_id in METHODS:
        tiles = [_logical_tile(row_map[(source_id, method_id)]) for source_id in source_ids]
        sheet = Image.new("RGBA", (3 * tile_width, tile_height), (250, 250, 250, 255))
        for index, tile in enumerate(tiles):
            sheet.alpha_composite(tile, (index * tile_width, 0))
        sheet.save(by_method / f"{method_id}.png", format="PNG", optimize=False)
    for method_id in ("D1", "D2"):
        tiles: list[Image.Image] = []
        for source_id in source_ids:
            row = row_map[(source_id, method_id)]
            intermediate = Path(row["intermediate_path"]) if row.get("intermediate_path") else None
            if method_id == "D2" and intermediate and intermediate.is_file():
                tiles.append(_audit_tile(intermediate, f"{method_id} {source_id} intermediate"))
            semantic = Path(row["semantic_path"])
            if semantic.is_file():
                tiles.append(_audit_tile(semantic, f"{method_id} {source_id} semantic"))
            logical = Path(row["logical_path"]) if row.get("logical_path") else None
            if logical and logical.is_file():
                tiles.append(_audit_tile(logical, f"{method_id} {source_id} PSE logical"))
        sheet = Image.new("RGBA", (4 * 220, max(1, (len(tiles) + 3) // 4) * 260), (250, 250, 250, 255))
        for index, tile in enumerate(tiles):
            sheet.alpha_composite(tile, ((index % 4) * 220, (index // 4) * 260))
        sheet.save(semantic_audit / f"{method_id}.png", format="PNG", optimize=False)


def _write_sidecar(path: Path, row: dict[str, Any], source_path: Path, pse_version: str) -> None:
    provider = row["report"]["semantic"]["provider"]
    payload: dict[str, Any] = {
        "method": row["method_id"],
        "source_id": row["source_id"],
        "source_sha256": _sha256(source_path),
        "semantic_image_sha256": _sha256(Path(row["semantic_path"])),
        "provider": provider.get("provider", "unknown"),
        "model": provider.get("model") or "grok-build",
        "prompt_sha256": hashlib.sha256(str(provider.get("prompt", "")).encode("utf-8")).hexdigest(),
        "pse_version": pse_version,
        "accepted": row.get("status") == "PASS_LOGICAL_MASTER",
        "logical_master_sha256": _sha256(Path(row["logical_path"])) if row.get("logical_path") and Path(row["logical_path"]).is_file() else None,
        "semantic_generation": provider,
    }
    if row["method_id"] == "D2" and row.get("intermediate_path") and "intermediate" in row["report"]:
        intermediate_provider = row["report"]["intermediate"]["provider"]
        payload["intermediate_sha256"] = _sha256(Path(row["intermediate_path"]))
        payload["intermediate_path"] = os.path.relpath(Path(row["intermediate_path"]), path.parent)
        payload["stage1_prompt_sha256"] = hashlib.sha256(str(intermediate_provider.get("prompt", "")).encode("utf-8")).hexdigest()
        payload["stage2_prompt_sha256"] = payload["prompt_sha256"]
        payload["intermediate_generation"] = intermediate_provider
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_reports(
    rows: list[dict[str, Any]],
    reports_root: Path,
    source_ids: list[str],
    *,
    run_label: str = "Smoke",
) -> None:
    reports_root.mkdir(parents=True, exist_ok=True)
    pse_fields = [
        "source_id", "method_id", "status", "semantic_status", "semantic_path", "intermediate_path", "logical_path",
        "subject_area_ratio", "edge_softness_ratio", "adjacent_transition_ratio", "palette_size", "subject_height",
        "binary_alpha", "isolated_ratio", "warnings",
    ]
    with (reports_root / "pse_metrics.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=pse_fields)
        writer.writeheader()
        for row in rows:
            quality = row.get("report", {}).get("semantic_quality", {}).get("metrics", {})
            cluster = quality.get("cluster_size_distribution", {})
            validation = row.get("report", {}).get("logical_validation", {}).get("metrics", {}) or {}
            writer.writerow({
                "source_id": row["source_id"], "method_id": row["method_id"], "status": row["status"],
                "semantic_status": row.get("semantic_status", ""), "semantic_path": row.get("semantic_path", ""),
                "intermediate_path": row.get("intermediate_path", ""), "logical_path": row.get("logical_path", ""),
                "subject_area_ratio": quality.get("subject_area_ratio", ""),
                "edge_softness_ratio": quality.get("edge_softness_ratio", ""),
                "adjacent_transition_ratio": quality.get("adjacent_transition_ratio", ""),
                "palette_size": validation.get("palette_size", cluster.get("opaque_color_count", "")),
                "subject_height": validation.get("subject_height", ""),
                "binary_alpha": validation.get("binary_alpha", ""),
                "isolated_ratio": validation.get("isolated_ratio", ""),
                "warnings": row.get("warnings", []),
            })
    objective_fields = ["source_id", "method_id", "status", "path", "width", "height", "palette_size", "alpha_fringe_pixels", "isolated_pixel_count", "occupied_bbox_ratio", "target_height_error", "sha256"]
    with (reports_root / "objective_scores.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=objective_fields)
        writer.writeheader()
        writer.writerows({field: row.get(field) for field in objective_fields} for row in rows)
    logical_fields = [
        "source_id", "method_id", "status", "semantic_status", "pse_status", "logical_validation_status",
        "logical_path", "width", "height", "palette_size", "subject_height", "binary_alpha", "isolated_ratio", "warnings",
    ]
    with (reports_root / "logical_master_results.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=logical_fields)
        writer.writeheader()
        for row in rows:
            report = row.get("report", {})
            validation = report.get("logical_validation", {}) or {}
            metrics = validation.get("metrics", {}) or {}
            writer.writerow({
                "source_id": row["source_id"],
                "method_id": row["method_id"],
                "status": row["status"],
                "semantic_status": row.get("semantic_status", ""),
                "pse_status": (report.get("pse", {}) or {}).get("status", ""),
                "logical_validation_status": validation.get("status", ""),
                "logical_path": row.get("logical_path", ""),
                "width": row.get("width", ""),
                "height": row.get("height", ""),
                "palette_size": metrics.get("palette_size", row.get("palette_size", "")),
                "subject_height": metrics.get("subject_height", ""),
                "binary_alpha": metrics.get("binary_alpha", ""),
                "isolated_ratio": metrics.get("isolated_ratio", ""),
                "warnings": row.get("warnings", []),
            })
    human_fields = ["source_id", "method_id", "identity_fidelity", "silhouette_readability", "face_readability", "costume_readability", "asymmetric_feature_preservation", "pixel_cluster_quality", "palette_cleanliness", "outline_quality", "cleanup_burden", "production_readiness", "notes"]
    with (reports_root / "human_scores.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=human_fields)
        writer.writeheader()
        for source_id in source_ids:
            for method_id in METHODS:
                writer.writerow({"source_id": source_id, "method_id": method_id})

    valid = [
        row for row in rows
        if row.get("status") in {"PASS", "PASS_LOGICAL_MASTER"} and row.get("palette_size") is not None
    ]
    means: dict[str, float] = {}
    for method_id in METHODS:
        values = [float(row["palette_size"]) for row in valid if row["method_id"] == method_id]
        if values:
            means[method_id] = round(sum(values) / len(values), 3)
    if means:
        best = min(means.values())
        tied = [method_id for method_id in METHODS if means.get(method_id) == best]
        proxy_line = f"- Objective palette-size proxy: {tied[0]} ({best})" if len(tied) == 1 else f"- Objective palette-size proxy: TIE — {', '.join(tied)} ({best})"
    else:
        proxy_line = "- Objective palette-size proxy: unavailable (no valid logical outputs)"
    status_counts = {
        status: sum(1 for row in rows if row["status"] == status)
        for status in sorted({row["status"] for row in rows})
    }
    summary = [
        f"# Pixel Master Benchmark V2 — Phase 2B {run_label}",
        "",
        "## Scope",
        "",
        f"- Sources: {len(source_ids)} ({', '.join(source_ids)})",
        f"- Methods: {len(METHODS)} ({', '.join(METHODS)})",
        "- Compared artifact: validated logical master only",
        "- Preview: 4× nearest-neighbor for every logical tile",
        "- C1/C2 strict capability results remain in the Phase 2A appendix and are not mixed into this ranking.",
        "",
        "## Execution result",
        "",
        f"- Logical comparisons: {len(source_ids)} sources × {len(METHODS)} methods = {len(rows)} method results",
        f"- Status: {', '.join(f'{status}={count}' for status, count in status_counts.items())}",
        proxy_line,
        "- Objective palette-size proxy is not a visual-quality decision; no visual ranking is emitted.",
        "- Human review: pending; `human_scores.csv` intentionally remains blank.",
        "",
        "## Artifacts",
        "",
        "- `semantic/` and `intermediate/` — AI audit artifacts only",
        "- `logical/` — accepted PSE logical masters only",
        "- `validation/` — semantic quality, PSE, and logical-master records",
        "- `sheets/by_source/` and `sheets/by_method/` — logical-only contact sheets",
        "- `sheets/semantic_audit/` — semantic/intermediate audit sheets",
        "- `reports/pse_metrics.csv` — PSE and semantic quality metrics",
        "- `reports/logical_master_results.csv` — final logical master acceptance records",
    ]
    if len(source_ids) == 9:
        summary.extend([
            "",
            "## R08 hard case",
            "",
            "R08 is recorded separately as the painterly/low-contrast hard case. No threshold or rescue policy was changed for it.",
            "",
        ])
        for method_id in ("D1", "D2"):
            row = next((item for item in rows if item["source_id"] == "R08" and item["method_id"] == method_id), None)
            if row is None:
                continue
            report = row.get("report", {})
            quality = report.get("semantic_quality", {})
            summary.append(
                f"- {method_id}: semantic={row.get('semantic_status', 'unknown')}; "
                f"pse={(report.get('pse', {}) or {}).get('status', 'unknown')}; "
                f"logical={row.get('status', 'unknown')}; "
                f"warnings={','.join(item.get('code', '') for item in quality.get('warnings', [])) or 'none'}"
            )
    (reports_root / "smoke_summary.md").write_text("\n".join(summary) + "\n", encoding="utf-8")
    (reports_root / "benchmark_summary.md").write_text("\n".join(summary) + "\n", encoding="utf-8")


def run_phase_2b(
    context: V2RunContext,
    *,
    output_root: Path,
    provider: str,
    force: bool = False,
    run_label: str = "Smoke",
) -> list[dict[str, Any]]:
    output_root = output_root.resolve()
    source_ids = [*context.tier_a_sources, *context.tier_b_sources]
    for folder in ("semantic", "intermediate", "logical", "validation"):
        for method_id in METHODS:
            (output_root / folder / method_id).mkdir(parents=True, exist_ok=True)
    manifest = {
        "kind": "pixel-master-phase2b-semantic-pse",
        "version": 1,
        "config": str(context.config_path),
        "sources": source_ids,
        "methods": list(METHODS),
        "provider": provider,
        "fixture_policy": "immutable-existing-files-only",
        "logical_preview_scale": 4,
        "strict_capability_appendix": "benchmark_v2/phase2A_rebench_128logical",
        "fixture_sha256": {
            fixture.source_id: fixture.actual_sha256
            for fixture in context.tier_b_fixtures.fixtures
        },
        "fixture_paths": {
            fixture.source_id: str(fixture.path)
            for fixture in context.tier_b_fixtures.fixtures
        },
        "run_label": run_label,
    }
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "run_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    reports_root = output_root / "reports"
    reports_root.mkdir(parents=True, exist_ok=True)
    (reports_root / "run_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    provenance_root = output_root / "provenance"
    rows: list[dict[str, Any]] = []
    options = _options(context)
    for source_id in source_ids:
        source_path = _source_path(context, source_id)
        with Image.open(source_path) as opened:
            source = opened.convert("RGBA")
        for method_id in METHODS:
            row: dict[str, Any] = {
                "source_id": source_id, "method_id": method_id, "method_label": METHOD_LABELS[method_id],
                "status": "PASS", "path": "", "logical_path": "", "semantic_path": "", "intermediate_path": "",
                "semantic_status": "not_applicable", "warnings": [], "report": {},
            }
            logical_path = output_root / "logical" / method_id / f"{source_id}.png"
            if method_id in {"A1", "A2", "B1"}:
                logical = shared_post_process(_run_local_method(method_id, source, options))
                if force or not logical_path.exists():
                    logical.save(logical_path, format="PNG", optimize=False)
                row.update({"path": str(logical_path), "logical_path": str(logical_path), "width": logical.width, "height": logical.height})
                row.update(objective_metrics(logical))
                rows.append(row)
                continue

            production_dir = output_root / "_production" / method_id / source_id
            if method_id == "D1":
                result = d1_semantic_pse_file(source_path, production_dir, provider=provider, options=SemanticPseOptions(), stem=source_id, workdir=output_root / "_work" / method_id / source_id)
                semantic_source = result.semantic_path
                intermediate_source = None
            else:
                result = d2_semantic_pse_file(source_path, production_dir, provider=provider, options=SemanticPseOptions(), stem=source_id, workdir=output_root / "_work" / method_id / source_id)
                semantic_source = result.semantic_path
                intermediate_source = result.intermediate_path
            semantic_output = output_root / "semantic" / method_id / f"{source_id}.png"
            semantic_output.parent.mkdir(parents=True, exist_ok=True)
            semantic_output.unlink(missing_ok=True)
            shutil.copyfile(semantic_source, semantic_output)
            intermediate_output = ""
            if intermediate_source is not None:
                intermediate_target = output_root / "intermediate" / method_id / f"{source_id}.png"
                intermediate_target.parent.mkdir(parents=True, exist_ok=True)
                intermediate_target.unlink(missing_ok=True)
                shutil.copyfile(intermediate_source, intermediate_target)
                intermediate_output = str(intermediate_target)
            row.update({
                "status": result.report.get("status", "FAIL_PSE"),
                "semantic_status": result.report.get("semantic_quality", {}).get("status", "unknown"),
                "semantic_path": str(semantic_output),
                "intermediate_path": intermediate_output,
                "report": result.report,
                "warnings": result.report.get("semantic_quality", {}).get("warnings", []) + result.report.get("logical_validation", {}).get("warnings", []) if isinstance(result.report.get("logical_validation"), dict) else result.report.get("semantic_quality", {}).get("warnings", []),
            })
            if result.accepted_path is not None:
                shutil.copyfile(result.accepted_path, logical_path)
                row.update({"path": str(logical_path), "logical_path": str(logical_path)})
                with Image.open(logical_path) as accepted:
                    row.update(objective_metrics(accepted.convert("RGBA")))
            else:
                row.update({"width": None, "height": None, "palette_size": None, "alpha_fringe_pixels": None, "isolated_pixel_count": None, "occupied_bbox_ratio": None, "target_height_error": None, "sha256": None})
            validation_path = output_root / "validation" / method_id / f"{source_id}.json"
            validation_path.write_text(json.dumps(result.report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            provenance_path = provenance_root / method_id / f"{source_id}.json"
            provenance_path.parent.mkdir(parents=True, exist_ok=True)
            _write_sidecar(provenance_path, row, source_path, PSE_VERSION)
            rows.append(row)
    _write_sheets(rows, output_root / "sheets", source_ids)
    _write_reports(rows, reports_root, source_ids, run_label=run_label)
    return rows


__all__ = ["METHODS", "run_phase_2b"]
