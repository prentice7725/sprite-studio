#!/usr/bin/env python3
"""Run Phase 2B smoke using pre-generated GPT Image semantic artifacts.

The GPT Image calls are intentionally performed by the built-in image tool, not
by the Grok/Codex CLI adapters. This runner only stages those immutable outputs
and executes the deterministic semantic-quality, PSE, logical-master, and
reporting gates.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Any

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from studio.static_mode.pixelize.d1_d2 import (  # noqa: E402
    SemanticPseOptions,
    _finalize,
    _paths,
)
from studio.static_mode.pixelize.structure_extractor import PSE_VERSION  # noqa: E402
from tools import pixel_master_benchmark_phase2b_execute as executor  # noqa: E402
from tools import pixel_master_benchmark_v2 as preparation  # noqa: E402
from tools.pixel_master_benchmark_v2_execute import (  # noqa: E402
    _options,
    _run_local_method,
    _source_path,
    objective_metrics,
    shared_post_process,
)


DEFAULT_CONFIG = ROOT / "benchmark_v2" / "configs" / "benchmark_matrix_r00_r08.json"
DEFAULT_MANIFEST = ROOT / "benchmark_v2" / "configs" / "tier_b_fixtures_r00_r08.json"
DEFAULT_SOURCE_ROOT = ROOT / "benchmark_v2" / "sources" / "tier_b"
DEFAULT_OUT = ROOT / "benchmark_v2" / "phase2B_semantic_pse" / "smoke_gpt_image"
SMOKE_SOURCES = ("R00", "R03", "R06")
METHODS = ("A1", "A2", "B1", "D1", "D2")
GPT_PROVIDER = "gpt-image"
GPT_MODEL = "gpt-image"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _provider_record(prompt: str, output_path: Path, refs: list[Path]) -> dict[str, Any]:
    return {
        "provider": GPT_PROVIDER,
        "model": GPT_MODEL,
        "prompt": prompt,
        "out": str(output_path.resolve()),
        "raw": str(output_path.resolve()),
        "raw_sha256": _sha256(output_path),
        "refs": [str(ref.resolve()) for ref in refs],
        "tool": "built-in image_gen",
        "generation_mode": "direct_gpt_image_tool",
    }


def _prompt(label: str) -> str:
    return label


def _stage_semantic(
    *,
    source_path: Path,
    output_root: Path,
    method_id: str,
    source_id: str,
    raw_semantic: Path,
    raw_intermediate: Path | None,
    source_prompt: str,
    intermediate_prompt: str | None = None,
) -> dict[str, Any]:
    production_dir = output_root / "_production" / method_id / source_id
    semantic_path, logical_path, preview_path, palette_path, report_path = _paths(production_dir, source_id)
    shutil.copyfile(raw_semantic, semantic_path)
    intermediate_info: dict[str, Any] | None = None
    if raw_intermediate is not None:
        intermediate_path = production_dir / "intermediate" / f"{source_id}.png"
        intermediate_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(raw_intermediate, intermediate_path)
        intermediate_info = {
            "path": str(intermediate_path.resolve()),
            "provider": _provider_record(
                intermediate_prompt or "GPT Image semantic stage 1",
                raw_intermediate,
                [source_path],
            ),
        }

    semantic_provider = _provider_record(
        source_prompt,
        raw_semantic,
        [source_path] + ([raw_intermediate] if raw_intermediate is not None else []),
    )
    accepted, report = _finalize(
        source_path=source_path,
        semantic_path=semantic_path,
        logical_path=logical_path,
        preview_path=preview_path,
        palette_path=palette_path,
        report_path=report_path,
        strategy="semantic_d1_pse" if method_id == "D1" else "semantic_d2_pse",
        semantic_provider=semantic_provider,
        options=SemanticPseOptions(),
        intermediate=intermediate_info,
    )
    logical_path_value = str(logical_path) if accepted is not None else ""
    row: dict[str, Any] = {
        "source_id": source_id,
        "method_id": method_id,
        "method_label": method_id,
        "status": report.get("status", "FAIL_PSE"),
        "path": logical_path_value,
        "logical_path": logical_path_value,
        "semantic_path": str(semantic_path),
        "intermediate_path": str(intermediate_info["path"]) if intermediate_info else "",
        "semantic_status": report.get("semantic_quality", {}).get("status", "unknown"),
        "warnings": report.get("semantic_quality", {}).get("warnings", [])
        + (report.get("logical_validation", {}) or {}).get("warnings", []),
        "report": report,
    }
    if accepted is not None:
        with Image.open(accepted) as opened:
            row.update(objective_metrics(opened.convert("RGBA")))
    else:
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
    return row


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    output_root = args.out if args.out.is_absolute() else ROOT / args.out
    context = preparation.prepare_run(
        config_path=DEFAULT_CONFIG,
        output_root=output_root,
        methods=("A1", "A2", "B1"),
        tier_a_sources=(),
        tier_b_sources=SMOKE_SOURCES,
        manifest_path=DEFAULT_MANIFEST,
        tier_b_root=DEFAULT_SOURCE_ROOT,
    )
    output_root.mkdir(parents=True, exist_ok=True)
    manifest = {
        "kind": "pixel-master-phase2b-semantic-pse",
        "version": 1,
        "config": str(context.config_path),
        "sources": list(SMOKE_SOURCES),
        "methods": list(METHODS),
        "provider": GPT_PROVIDER,
        "model": GPT_MODEL,
        "semantic_provider": "OpenAI GPT Image via built-in image_gen",
        "fixture_policy": "immutable-existing-files-only",
        "logical_preview_scale": 4,
        "fixture_sha256": {fixture.source_id: fixture.actual_sha256 for fixture in context.tier_b_fixtures.fixtures},
        "fixture_paths": {fixture.source_id: str(fixture.path) for fixture in context.tier_b_fixtures.fixtures},
        "run_label": "GPT Image smoke R00/R03/R06",
    }
    (output_root / "run_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    reports_root = output_root / "reports"
    reports_root.mkdir(parents=True, exist_ok=True)
    (reports_root / "run_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    provenance_root = output_root / "provenance"
    options = _options(context)
    rows: list[dict[str, Any]] = []
    for source_id in SMOKE_SOURCES:
        source_path = _source_path(context, source_id)
        with Image.open(source_path) as opened:
            source = opened.convert("RGBA")
        for method_id in ("A1", "A2", "B1"):
            logical = shared_post_process(_run_local_method(method_id, source, options))
            logical_path = output_root / "logical" / method_id / f"{source_id}.png"
            logical_path.parent.mkdir(parents=True, exist_ok=True)
            logical.save(logical_path, format="PNG", optimize=False)
            row: dict[str, Any] = {
                "source_id": source_id,
                "method_id": method_id,
                "method_label": method_id,
                "status": "PASS",
                "path": str(logical_path),
                "logical_path": str(logical_path),
                "semantic_path": "",
                "intermediate_path": "",
                "semantic_status": "not_applicable",
                "warnings": [],
                "report": {},
            }
            row.update(objective_metrics(logical))
            rows.append(row)

        d1_raw = output_root / "_gpt" / "D1" / source_id / "raw.png"
        d2_stage1 = output_root / "_gpt" / "D2" / source_id / "stage1.png"
        d2_stage2 = output_root / "_gpt" / "D2" / source_id / "stage2.png"
        d1 = _stage_semantic(
            source_path=source_path,
            output_root=output_root,
            method_id="D1",
            source_id=source_id,
            raw_semantic=d1_raw,
            raw_intermediate=None,
            source_prompt=_prompt("GPT Image D1 semantic redraw"),
        )
        d2 = _stage_semantic(
            source_path=source_path,
            output_root=output_root,
            method_id="D2",
            source_id=source_id,
            raw_semantic=d2_stage2,
            raw_intermediate=d2_stage1,
            source_prompt=_prompt("GPT Image D2 stage2 semantic redraw"),
            intermediate_prompt=_prompt("GPT Image D2 stage1 semantic redraw"),
        )
        rows.extend((d1, d2))
        for row in (d1, d2):
            provenance_path = provenance_root / row["method_id"] / f"{source_id}.json"
            provenance_path.parent.mkdir(parents=True, exist_ok=True)
            executor._write_sidecar(provenance_path, row, source_path, PSE_VERSION)

    executor._write_sheets(rows, output_root / "sheets", list(SMOKE_SOURCES))
    executor._write_reports(rows, reports_root, list(SMOKE_SOURCES), run_label="GPT Image smoke R00/R03/R06")
    rows_by_method = {method: [row for row in rows if row["method_id"] == method] for method in METHODS}
    d_rows = rows_by_method["D1"] + rows_by_method["D2"]
    d_failures = [row for row in d_rows if row["status"] != "PASS_LOGICAL_MASTER"]
    summary_path = reports_root / "smoke_summary.md"
    summary = summary_path.read_text(encoding="utf-8")
    summary += "\n## GPT Image provider gate\n\n"
    summary += "- Semantic provider: OpenAI GPT Image via built-in `image_gen`; Grok was not used.\n"
    summary += "- D1/D2 order: GPT Image semantic output → PSE → logical master validator.\n"
    summary += "- Rescue policy: none; no LANCZOS, bilinear, BOX, threshold, or palette rescue.\n"
    summary += f"- D1 logical masters: {sum(row['status'] == 'PASS_LOGICAL_MASTER' for row in rows_by_method['D1'])}/3\n"
    summary += f"- D2 logical masters: {sum(row['status'] == 'PASS_LOGICAL_MASTER' for row in rows_by_method['D2'])}/3\n"
    if d_failures:
        summary += "- Recommendation: STOP — not all six D1/D2 logical masters were accepted.\n"
    else:
        summary += "- Recommendation: GO — all six D1/D2 smoke logical masters were accepted; full R00–R08 may proceed.\n"
    summary_path.write_text(summary, encoding="utf-8")
    (reports_root / "benchmark_summary.md").write_text(summary, encoding="utf-8")
    print(f"GPT Image smoke complete: {len(rows)} method results")
    print(f"D1 logical masters: {sum(row['status'] == 'PASS_LOGICAL_MASTER' for row in rows_by_method['D1'])}/3")
    print(f"D2 logical masters: {sum(row['status'] == 'PASS_LOGICAL_MASTER' for row in rows_by_method['D2'])}/3")
    print("recommendation:", "STOP" if d_failures else "GO")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
