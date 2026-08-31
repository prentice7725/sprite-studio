# SPDX-License-Identifier: Apache-2.0
"""R0-R3 repair detection, safety and persistence contracts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from studio.backend import repair_service
from studio.core.repair import RepairAnalyzer, RepairPipeline, RepairProfile, TemporalRepairEngine


BLUE = (60, 90, 180, 255)
DARK = (20, 24, 32, 255)


def _canvas(size: int = 16) -> Image.Image:
    return Image.new("RGBA", (size, size), (0, 0, 0, 0))


def test_analyzer_finds_and_safe_engine_repairs_one_pixel_hole() -> None:
    frame = _canvas()
    ImageDraw.Draw(frame).rectangle((3, 3, 12, 12), fill=BLUE)
    frame.putpixel((8, 10), (0, 0, 0, 0))
    profile = RepairProfile(protected_regions=())

    candidates = RepairAnalyzer().analyze(frame, profile=profile)
    hole = next(candidate for candidate in candidates if candidate.type == "small_hole")
    result = RepairPipeline().repair([frame], state="side_idle", profile=profile)

    assert hole.pixels == ((8, 10),)
    assert result.frames[0].getpixel((8, 10)) == BLUE
    assert {change.rule for change in result.changes} == {"small_hole"}


def test_face_region_hole_is_reported_but_never_auto_applied() -> None:
    frame = _canvas()
    ImageDraw.Draw(frame).rectangle((3, 2, 12, 13), fill=BLUE)
    frame.putpixel((8, 4), (0, 0, 0, 0))

    candidates = RepairAnalyzer().analyze(frame)
    hole = next(candidate for candidate in candidates if candidate.type == "small_hole")
    result = RepairPipeline().repair([frame], state="side_idle")

    assert hole.protected is True
    assert result.frames[0].getpixel((8, 4))[3] == 0
    assert any(item["reason"] == "protected-region" for item in result.skipped)


def test_outline_gap_and_orphan_are_repaired_without_new_palette_color() -> None:
    frame = _canvas()
    draw = ImageDraw.Draw(frame)
    draw.rectangle((3, 5, 12, 8), fill=DARK)
    draw.rectangle((3, 6, 12, 8), fill=BLUE)
    frame.putpixel((8, 5), (0, 0, 0, 0))
    frame.putpixel((14, 14), DARK)
    profile = RepairProfile(protected_regions=(), max_added_ratio=0.1)

    candidates = RepairAnalyzer().analyze(frame, profile=profile)
    assert {candidate.type for candidate in candidates} >= {"outline_gap", "orphan_pixel"}
    result = RepairPipeline().repair([frame], state="side_idle", profile=profile)

    assert result.frames[0].getpixel((8, 5)) == DARK
    assert result.frames[0].getpixel((14, 14))[3] == 0
    assert {color for color in result.frames[0].get_flattened_data() if color[3] > 0} == {DARK, BLUE}


def test_temporal_majority_restores_idle_edge_loss_but_not_attack_automatically() -> None:
    previous = _canvas()
    ImageDraw.Draw(previous).rectangle((5, 5, 9, 9), fill=BLUE)
    current = previous.copy()
    current.putpixel((7, 5), (0, 0, 0, 0))
    following = previous.copy()
    profile = RepairProfile(protected_regions=(), max_added_ratio=0.1)

    idle_candidates = TemporalRepairEngine().analyze(
        previous, current, following, frame_index=1, state="side_idle", profile=profile,
    )
    attack_candidates = TemporalRepairEngine().analyze(
        previous, current, following, frame_index=1, state="side_attack", profile=profile,
    )

    assert any(candidate.pixels == ((7, 5),) and candidate.confidence >= 0.95 for candidate in idle_candidates)
    assert any(candidate.pixels == ((7, 5),) and candidate.confidence < 0.95 for candidate in attack_candidates)
    attack_result = RepairPipeline().repair(
        [previous, current, following], state="side_attack", profile=profile,
    )
    assert attack_result.frames[1].getpixel((7, 5))[3] == 0


def test_directional_thin_feature_bridge_repairs_two_cell_weapon_break() -> None:
    frame = _canvas()
    draw = ImageDraw.Draw(frame)
    draw.line((2, 8, 13, 8), fill=DARK, width=1)
    frame.putpixel((7, 8), (0, 0, 0, 0))
    frame.putpixel((8, 8), (0, 0, 0, 0))
    profile = RepairProfile(protected_regions=(), max_added_ratio=0.5)

    result = RepairPipeline().repair([frame], state="side_attack", profile=profile)

    assert result.frames[0].getpixel((7, 8)) == DARK
    assert result.frames[0].getpixel((8, 8)) == DARK
    assert any(change.rule == "thin_feature_break" for change in result.changes)


def _repair_run(tmp_path: Path) -> tuple[Path, Path]:
    run_dir = tmp_path / "run"
    refined_dir = run_dir / "frames" / "side" / "idle" / "refined"
    refined_dir.mkdir(parents=True)
    request = {
        "layout": "taxonomy/v1",
        "directions": {"set": ["side"], "mirror": {}},
        "states": {"side_idle": {"frames": 3}},
        "cell": {"width": 32, "height": 32},
    }
    (run_dir / "sprite-request.json").write_text(json.dumps(request), encoding="utf-8")
    studio_dir = run_dir / "studio"
    studio_dir.mkdir()
    (studio_dir / "studio.json").write_text(json.dumps({"config": {"repair": {"protected_regions": []}}}), encoding="utf-8")
    for index in range(3):
        logical = _canvas(16)
        ImageDraw.Draw(logical).rectangle((4, 4, 11, 12), fill=BLUE)
        if index == 1:
            logical.putpixel((8, 9), (0, 0, 0, 0))
        logical.resize((32, 32), Image.Resampling.NEAREST).save(refined_dir / f"frame-{index}.png")
    (refined_dir / "refine.report.json").write_text(json.dumps({"shared": {"logical_size": [16, 16]}}), encoding="utf-8")
    return run_dir, refined_dir


def test_backend_persists_proposals_repaired_frames_diff_and_revision(tmp_path: Path) -> None:
    run_dir, refined_dir = _repair_run(tmp_path)
    before = (refined_dir / "frame-1.png").read_bytes()

    analysis = repair_service.analyze_state(run_dir, "side_idle")
    log = repair_service.repair_state(run_dir, "side_idle")
    data = repair_service.review_data(run_dir, "side_idle")

    assert analysis["candidate_count"] >= 1
    assert log["source_revision"] == analysis["source_revision"]
    assert len(data["proposal_files"]) == 3
    assert len(data["repaired_files"]) == 3
    assert len(data["diff_files"]) == 3
    assert (refined_dir / "frame-1.png").read_bytes() == before
    with Image.open(data["repaired_files"][1]) as repaired:
        assert repaired.getpixel((16, 18)) == BLUE


def test_rejected_candidate_is_removed_from_derived_output_and_stale_output_is_ignored(tmp_path: Path) -> None:
    run_dir, refined_dir = _repair_run(tmp_path)
    analysis = repair_service.analyze_state(run_dir, "side_idle")
    repair_service.repair_state(run_dir, "side_idle")
    hole_id = next(candidate["id"] for candidate in analysis["candidates"]
                   if candidate["type"] == "small_hole" and candidate["frame"] == 1)

    repair_service.decide_candidates(run_dir, "side_idle", {hole_id}, accept=False)
    repaired_path = repair_service.repaired_files(run_dir, "side_idle")[1]
    with Image.open(repaired_path) as repaired:
        assert repaired.getpixel((16, 18))[3] == 0

    with Image.open(refined_dir / "frame-0.png") as opened:
        changed = opened.convert("RGBA")
    changed.putpixel((0, 0), BLUE)
    changed.save(refined_dir / "frame-0.png")
    assert repair_service.repaired_files(run_dir, "side_idle") == []


def test_ai_micro_fix_job_accepts_only_masked_shared_palette_changes(tmp_path: Path) -> None:
    run_dir, _refined_dir = _repair_run(tmp_path)
    analysis = repair_service.analyze_state(run_dir, "side_idle")
    candidate = next(item for item in analysis["candidates"]
                     if item["type"] == "small_hole" and item["frame"] == 1)
    job = repair_service.prepare_ai_micro_fix(run_dir, "side_idle", {candidate["id"]})
    with Image.open(job["before_path"]) as opened:
        result = opened.convert("RGBA")
    x, y = candidate["pixels"][0]
    result.putpixel((x, y), BLUE)
    result_path = tmp_path / "ai-result.png"
    result.save(result_path)

    log = repair_service.apply_ai_micro_fix(run_dir, "side_idle", job["job_id"], result_path)

    assert log["ai_micro_fix"]["pixels_changed"] == 1
    assert log["ai_micro_fix"]["candidate_ids"] == [candidate["id"]]
    with Image.open(repair_service.repaired_files(run_dir, "side_idle")[1]) as repaired:
        assert repaired.getpixel((x * 2, y * 2)) == BLUE


def test_ai_micro_fix_rejects_unmasked_change(tmp_path: Path) -> None:
    run_dir, _refined_dir = _repair_run(tmp_path)
    analysis = repair_service.analyze_state(run_dir, "side_idle")
    candidate = next(item for item in analysis["candidates"]
                     if item["type"] == "small_hole" and item["frame"] == 1)
    job = repair_service.prepare_ai_micro_fix(run_dir, "side_idle", {candidate["id"]})
    with Image.open(job["before_path"]) as opened:
        result = opened.convert("RGBA")
    result.putpixel((0, 0), BLUE)
    result_path = tmp_path / "invalid-ai-result.png"
    result.save(result_path)

    with pytest.raises(ValueError, match="unmasked pixel"):
        repair_service.apply_ai_micro_fix(run_dir, "side_idle", job["job_id"], result_path)
