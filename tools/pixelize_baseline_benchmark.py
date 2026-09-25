#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Run the deterministic image-to-pixel-master baseline on frozen Tier-B sources.

This benchmark checks pipeline behavior and emits human-inspection artifacts;
it does not rank aesthetic quality or select a visual winner.

    py -3.11 -m tools.pixelize_baseline_benchmark --out runs/pixelize-baseline
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Any, Iterable

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from studio.static_mode.pixelize import PixelizeOptions, pixelize_file, pixelize_image
from studio.static_mode.pixelize.resolution import SUPPORTED_LOGICAL_HEIGHTS
from tools.tier_b_fixture_guard import sha256_file, verify_tier_b_fixtures


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "studio" / "data" / "benchmark" / "pixelize_baseline.json"
RESULT_FIELDS = (
    "case_id",
    "category",
    "source_id",
    "source_preparation",
    "target_height",
    "status",
    "source_sha256",
    "prepared_source_sha256",
    "source_width",
    "source_height",
    "subject_width",
    "subject_height",
    "subject_bbox",
    "logical_width",
    "logical_height",
    "palette_size",
    "validation_pass",
    "deterministic_repeat",
    "source_artifact",
    "subject_artifact",
    "logical_artifact",
    "preview_4x_artifact",
    "contact_sheet",
    "failure_reason",
    "human_visual_score",
    "human_notes",
)


class PixelizeBaselineError(RuntimeError):
    """The baseline could not safely or completely execute."""


def _json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PixelizeBaselineError(f"cannot read benchmark config {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise PixelizeBaselineError(f"benchmark config must contain a JSON object: {path}")
    return payload


def _relative_path(value: str) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (ROOT / path).resolve()


def _digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _derived_transparent(source_path: Path, destination: Path) -> None:
    """Create a documented test variant by keying near-border chroma noise."""
    with Image.open(source_path) as opened:
        rgb = np.asarray(opened.convert("RGB"), dtype=np.uint8)
    border = np.concatenate((rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]), axis=0)
    colors, counts = np.unique(border, axis=0, return_counts=True)
    background = colors[int(np.argmax(counts))]
    keyed = np.empty((rgb.shape[0], rgb.shape[1], 4), dtype=np.uint8)
    keyed[:, :, :3] = rgb
    distance = np.sqrt(np.sum((rgb.astype(np.float32) - background.astype(np.float32)) ** 2, axis=2))
    keyed[:, :, 3] = np.where(distance > 20.0, 255, 0).astype(np.uint8)
    if not np.any(keyed[:, :, 3] == 0) or not np.any(keyed[:, :, 3] == 255):
        raise PixelizeBaselineError(f"dominant-border chroma key did not separate background and subject: {source_path}")
    alpha = keyed[:, :, 3]
    border_alpha = np.concatenate((alpha[0], alpha[-1], alpha[:, 0], alpha[:, -1]))
    if np.any(border_alpha >= 128):
        raise PixelizeBaselineError(f"transparent fixture preparation left foreground on the image border: {source_path}")
    Image.fromarray(keyed, mode="RGBA").save(destination, format="PNG")


def _checkerboard(size: tuple[int, int], tile: int = 16) -> Image.Image:
    width, height = size
    board = Image.new("RGB", size, (54, 56, 62))
    draw = ImageDraw.Draw(board)
    for y in range(0, height, tile):
        for x in range(0, width, tile):
            if (x // tile + y // tile) % 2:
                draw.rectangle((x, y, min(width - 1, x + tile - 1), min(height - 1, y + tile - 1)), fill=(76, 78, 84))
    return board


def _fit_panel(image: Image.Image, panel_size: tuple[int, int]) -> Image.Image:
    """Presentation-only fit; never feeds back into the measured pipeline."""
    panel = _checkerboard(panel_size)
    rgba = image.convert("RGBA")
    rgba.thumbnail((panel_size[0] - 24, panel_size[1] - 24), Image.Resampling.LANCZOS)
    x = (panel_size[0] - rgba.width) // 2
    y = (panel_size[1] - rgba.height) // 2
    panel.paste(rgba, (x, y), rgba.getchannel("A"))
    return panel


def _contact_sheet(
    *,
    source_path: Path,
    subject_path: Path,
    logical_path: Path,
    preview_path: Path,
    output_path: Path,
    title: str,
) -> None:
    panel_width, panel_height, label_height = 420, 540, 48
    labels = ("Source", "Extracted subject", "Logical master (4× NEAREST view)", "Saved 4× NEAREST preview")
    sheet = Image.new("RGB", (panel_width * len(labels), panel_height + label_height), (28, 30, 34))
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("segoeui.ttf", 17)
        title_font = ImageFont.truetype("segoeui.ttf", 18)
    except OSError:
        font = ImageFont.load_default()
        title_font = font
    draw.text((12, 10), title, fill=(245, 245, 245), font=title_font)
    paths = (source_path, subject_path, logical_path, preview_path)
    for index, (label, path) in enumerate(zip(labels, paths)):
        left = index * panel_width
        draw.text((left + 12, 30), label, fill=(210, 215, 225), font=font)
        with Image.open(path) as opened:
            view = opened.convert("RGBA")
            if index == 2:
                view = view.resize((view.width * 4, view.height * 4), Image.Resampling.NEAREST)
            fitted = _fit_panel(view, (panel_width, panel_height))
        sheet.paste(fitted, (left, label_height))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output_path, format="PNG")


def _options(payload: dict[str, Any], target_height: int) -> PixelizeOptions:
    values = dict(payload)
    values["target_size"] = target_height
    try:
        return PixelizeOptions(**values)
    except (TypeError, ValueError) as exc:
        raise PixelizeBaselineError(f"invalid pixelize options for target height {target_height}: {exc}") from exc


def _case_source(case: dict[str, Any], fixture_paths: dict[str, Path], case_dir: Path) -> tuple[Path, str, str]:
    source_id = str(case["source_id"])
    original = fixture_paths[source_id]
    source_copy = case_dir / "input" / "source.png"
    source_copy.parent.mkdir(parents=True, exist_ok=True)
    source_hash = sha256_file(original)
    preparation = case.get("preparation")
    if preparation is None:
        shutil.copyfile(original, source_copy)
    elif preparation == "dominant_border_distance_gt_20_to_alpha":
        _derived_transparent(original, source_copy)
    else:
        raise PixelizeBaselineError(f"unsupported fixture preparation for {case.get('case_id')}: {preparation}")
    return source_copy, source_hash, sha256_file(source_copy)


def _save_manifest(output_root: Path, manifest: dict[str, Any]) -> None:
    (output_root / "run_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _write_results(output_root: Path, rows: list[dict[str, Any]]) -> None:
    with (output_root / "logical_master_results.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=RESULT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _write_summary(output_root: Path, manifest: dict[str, Any]) -> None:
    rows = manifest["results"]
    passed = sum(row["status"] == "PASS" for row in rows)
    failed = len(rows) - passed
    lines = [
        "# Deterministic Pixelize Baseline",
        "",
        f"- Run ID: `{manifest['run_id']}`",
        f"- Source fixtures verified: {len(manifest['verified_sources'])}",
        f"- Conversion cases: {len(rows)}",
        f"- Validation/repeatability: {passed} PASS / {failed} FAIL",
        f"- Target logical heights: {', '.join(str(value) for value in manifest['target_heights'])}",
        "- Visual quality winner: **not assigned** (requires human review).",
        "- Human score and notes remain blank in `logical_master_results.csv`.",
        "",
        "## Runtime results",
        "",
        "| Case | Category | Height | Validation | Deterministic repeat | Status |",
        "|---|---|---:|---|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['case_id']} | {row['category']} | {row['target_height']} | "
            f"{'PASS' if row['validation_pass'] else 'FAIL'} | "
            f"{'PASS' if row['deterministic_repeat'] else 'FAIL'} | {row['status']} |"
        )
    lines.extend(("", "## Visual review", "", "Open the case sheets under `by_source/`. They show source, extracted subject, logical master rendered for inspection at 4× NEAREST, and the saved 4× NEAREST preview. The logical master and preview are intentionally not used to auto-rank visual quality.", ""))
    (output_root / "baseline_summary.md").write_text("\n".join(lines), encoding="utf-8")


def run_baseline(
    output_dir: Path,
    *,
    config_path: Path = DEFAULT_CONFIG,
) -> dict[str, Any]:
    """Verify immutable inputs, convert each case, and write audit artifacts."""
    output_root = output_dir.resolve()
    if output_root.exists() and any(output_root.iterdir()):
        raise PixelizeBaselineError(f"refusing to overwrite non-empty benchmark output directory: {output_root}")
    config = _json(config_path.resolve())
    if config.get("kind") != "sprite-studio-deterministic-pixelize-baseline" or config.get("version") != 1:
        raise PixelizeBaselineError(f"unsupported deterministic Pixelize baseline config: {config_path}")
    heights = tuple(int(value) for value in config.get("target_heights", ()))
    if not heights or any(value not in SUPPORTED_LOGICAL_HEIGHTS for value in heights):
        raise PixelizeBaselineError(f"target_heights must be a non-empty subset of {SUPPORTED_LOGICAL_HEIGHTS}")
    cases = config.get("cases")
    if not isinstance(cases, list) or not cases:
        raise PixelizeBaselineError("baseline config must list at least one case")
    case_ids = [str(case.get("case_id", "")) for case in cases if isinstance(case, dict)]
    if len(case_ids) != len(cases) or any(not item for item in case_ids) or len(set(case_ids)) != len(case_ids):
        raise PixelizeBaselineError("baseline case_id values must be unique non-empty strings")
    required_ids = tuple(dict.fromkeys(str(case["source_id"]) for case in cases))
    fixture_manifest = _relative_path(str(config["fixture_manifest"]))
    source_root = _relative_path(str(config["source_root"]))
    fixtures = verify_tier_b_fixtures(
        source_root=source_root,
        manifest_path=fixture_manifest,
        required_ids=required_ids,
    )
    fixture_paths = {fixture.source_id: fixture.path for fixture in fixtures.fixtures}
    output_root.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {
        "kind": "sprite-studio-deterministic-pixelize-baseline-run",
        "version": 1,
        "run_id": output_root.name,
        "config_path": str(config_path.resolve()),
        "config_sha256": sha256_file(config_path.resolve()),
        "fixture_manifest": str(fixture_manifest),
        "source_root": str(source_root),
        "target_heights": list(heights),
        "pixelize_options": config.get("pixelize_options", {}),
        "verified_sources": [
            {"source_id": fixture.source_id, "path": str(fixture.path), "sha256": fixture.actual_sha256}
            for fixture in fixtures.fixtures
        ],
        "results": [],
    }
    _save_manifest(output_root, manifest)
    rows: list[dict[str, Any]] = []

    for case in cases:
        case_id = str(case["case_id"])
        case_dir = output_root / "cases" / case_id
        input_path, source_hash, prepared_hash = _case_source(case, fixture_paths, case_dir)
        with Image.open(input_path) as opened:
            source_image = opened.convert("RGBA")
        for target_height in heights:
            relative_case_dir = Path("cases") / case_id / f"h{target_height}"
            artifacts_dir = output_root / relative_case_dir / "artifacts"
            options = _options(config.get("pixelize_options", {}), target_height)
            row: dict[str, Any] = {
                "case_id": case_id,
                "category": str(case.get("category", "unspecified")),
                "source_id": str(case["source_id"]),
                "source_preparation": str(case.get("preparation", "none")),
                "target_height": target_height,
                "status": "FAIL",
                "source_sha256": source_hash,
                "prepared_source_sha256": prepared_hash,
                "source_width": source_image.width,
                "source_height": source_image.height,
                "subject_width": "",
                "subject_height": "",
                "subject_bbox": "",
                "logical_width": "",
                "logical_height": "",
                "palette_size": "",
                "validation_pass": False,
                "deterministic_repeat": False,
                "source_artifact": str(input_path.relative_to(output_root)),
                "subject_artifact": "",
                "logical_artifact": "",
                "preview_4x_artifact": "",
                "contact_sheet": "",
                "failure_reason": "",
                "human_visual_score": "",
                "human_notes": "",
            }
            try:
                result = pixelize_file(input_path, artifacts_dir, options, stem="logical_master")
                with Image.open(input_path) as opened:
                    repeated, _, _ = pixelize_image(opened.convert("RGBA"), options)
                with Image.open(result.output_path) as opened:
                    accepted = opened.convert("RGBA")
                row.update({
                    "subject_width": result.report["subject_size"][0],
                    "subject_height": result.report["subject_size"][1],
                    "subject_bbox": json.dumps(result.subject_bbox),
                    "logical_width": result.logical_size[0],
                    "logical_height": result.logical_size[1],
                    "palette_size": len(result.palette),
                    "validation_pass": bool(result.report["validation"]["pass"]),
                    "deterministic_repeat": accepted.tobytes() == repeated.tobytes(),
                    "subject_artifact": str(result.subject_path.relative_to(output_root)),
                    "logical_artifact": str(result.output_path.relative_to(output_root)),
                    "preview_4x_artifact": str(result.preview_path.relative_to(output_root)),
                })
                row["status"] = "PASS" if row["validation_pass"] and row["deterministic_repeat"] else "FAIL"
                if row["status"] == "PASS":
                    sheet = output_root / "by_source" / f"{case_id}-h{target_height}.png"
                    _contact_sheet(
                        source_path=input_path,
                        subject_path=result.subject_path,
                        logical_path=result.output_path,
                        preview_path=result.preview_path,
                        output_path=sheet,
                        title=f"{case_id} · {row['category']} · logical height {target_height}",
                    )
                    row["contact_sheet"] = str(sheet.relative_to(output_root))
            except Exception as exc:  # retain and report every hard failure; never rescue it
                row["failure_reason"] = f"{type(exc).__name__}: {exc}"
            rows.append(row)
            manifest["results"].append(row)
            _save_manifest(output_root, manifest)

    _write_results(output_root, rows)
    _write_summary(output_root, manifest)
    return manifest


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path, help="new or empty, preferably ignored output directory")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args(argv)
    try:
        manifest = run_baseline(args.out, config_path=args.config)
    except Exception as exc:
        print(f"benchmark failed before completion: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    passed = sum(row["status"] == "PASS" for row in manifest["results"])
    failed = len(manifest["results"]) - passed
    print(f"deterministic Pixelize baseline: {passed} PASS / {failed} FAIL")
    print(f"summary: {(args.out.resolve() / 'baseline_summary.md')}")
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
