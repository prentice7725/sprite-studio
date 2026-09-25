# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw

from tools.pixelize_baseline_benchmark import PixelizeBaselineError, run_baseline
from tools.tier_b_fixture_guard import TierBFixtureError


def _fixture_manifest(tmp_path: Path, source_path: Path) -> Path:
    digest = hashlib.sha256(source_path.read_bytes()).hexdigest()
    manifest = tmp_path / "fixtures.json"
    manifest.write_text(json.dumps({
        "version": 1,
        "kind": "pixel-master-tier-b-fixtures",
        "source_root": "fixtures",
        "policy": "immutable-existing-files-only",
        "required_sources": [{"id": "R01", "file": "R01.png", "sha256": digest}],
    }), encoding="utf-8")
    return manifest


def _fixture_source(path: Path) -> None:
    image = Image.new("RGB", (96, 128), (0, 255, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((32, 10, 64, 42), fill=(244, 202, 160))
    draw.rectangle((26, 40, 70, 104), fill=(45, 80, 140))
    draw.line((48, 52, 48, 120), fill=(28, 24, 30), width=3)
    image.save(path)


def test_baseline_writes_provenance_validation_and_unranked_contact_sheet(tmp_path: Path):
    source_root = tmp_path / "fixtures"
    source_root.mkdir()
    source = source_root / "R01.png"
    _fixture_source(source)
    fixture_manifest = _fixture_manifest(tmp_path, source)
    config = tmp_path / "config.json"
    config.write_text(json.dumps({
        "kind": "sprite-studio-deterministic-pixelize-baseline",
        "version": 1,
        "fixture_manifest": str(fixture_manifest),
        "source_root": str(source_root),
        "target_heights": [128],
        "pixelize_options": {"palette_size": 16, "background": "cleanup"},
        "cases": [
            {"case_id": "R01-opaque", "source_id": "R01", "category": "opaque_background"},
            {"case_id": "R01-transparent", "source_id": "R01", "category": "derived_transparent_single_character", "preparation": "dominant_border_distance_gt_20_to_alpha"},
        ],
    }), encoding="utf-8")
    output = tmp_path / "run"

    manifest = run_baseline(output, config_path=config)

    assert len(manifest["verified_sources"]) == 1
    assert len(manifest["results"]) == 2
    assert all(row["status"] == "PASS" for row in manifest["results"])
    assert all(row["validation_pass"] and row["deterministic_repeat"] for row in manifest["results"])
    transparent_row = manifest["results"][1]
    assert transparent_row["source_preparation"] == "dominant_border_distance_gt_20_to_alpha"
    assert transparent_row["subject_width"] < transparent_row["source_width"]
    assert transparent_row["subject_height"] < transparent_row["source_height"]
    with Image.open(output / transparent_row["source_artifact"]) as prepared:
        assert prepared.mode == "RGBA"
        assert min(prepared.getchannel("A").getextrema()) == 0
    assert source.read_bytes() == (source_root / "R01.png").read_bytes()
    assert all((output / row["contact_sheet"]).is_file() for row in manifest["results"])
    assert all(row["human_visual_score"] == row["human_notes"] == "" for row in manifest["results"])
    with (output / "logical_master_results.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 2
    assert all(row["human_visual_score"] == "" for row in rows)
    report = json.loads((output / "run_manifest.json").read_text(encoding="utf-8"))
    assert report["results"] == manifest["results"]
    summary = (output / "baseline_summary.md").read_text(encoding="utf-8")
    assert "2 PASS / 0 FAIL" in summary
    assert "not assigned" in summary


def test_baseline_verifies_sources_before_creating_output(tmp_path: Path):
    output = tmp_path / "must-not-exist"
    config = tmp_path / "bad-config.json"
    config.write_text(json.dumps({
        "kind": "sprite-studio-deterministic-pixelize-baseline",
        "version": 1,
        "fixture_manifest": str(tmp_path / "missing.json"),
        "source_root": str(tmp_path / "missing-sources"),
        "target_heights": [128],
        "pixelize_options": {},
        "cases": [{"case_id": "missing", "source_id": "R01", "category": "fixture"}],
    }), encoding="utf-8")

    try:
        run_baseline(output, config_path=config)
    except TierBFixtureError:
        pass
    else:
        raise AssertionError("missing source manifest unexpectedly passed")
    assert not output.exists()


def test_baseline_refuses_to_overwrite_existing_results(tmp_path: Path):
    output = tmp_path / "existing"
    output.mkdir()
    marker = output / "preserve.txt"
    marker.write_text("user data", encoding="utf-8")
    config = tmp_path / "not-read.json"

    try:
        run_baseline(output, config_path=config)
    except PixelizeBaselineError as exc:
        assert "refusing to overwrite" in str(exc)
    else:
        raise AssertionError("non-empty output directory was unexpectedly accepted")
    assert marker.read_text(encoding="utf-8") == "user data"
