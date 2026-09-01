# SPDX-License-Identifier: Apache-2.0
"""Normalize quality gate enforcement across the Studio boundary.

`SPRITE_STUDIO_GENERATION_NORMALIZE_HARDENING_DIRECTIVE.md` §3/§5/§6: a
malformed normalize result must not silently become a usable row. These
tests cover the production (Studio) call chain that the plain
`sprite_studio.gen.normalize_grok_row` unit tests (tests/gen/) do not touch:
`spritegen_bridge.normalize_state` raising, `batch_service` stopping the
batch before Extract, and `curate.anchor` refusing to promote a
recovered/failed row.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from studio.backend import batch_service, spritegen_bridge
from sprite_studio.curate import anchor as anchor_mod

MAGENTA = (255, 0, 255)


def _sprite_request(*, frames: int = 4) -> dict:
    return {
        "version": 1,
        "kind": "sprite-studio-request",
        "engine": "component-row",
        "character": {"id": "gatebot", "description": "gate fixture", "base_image": None},
        "cell": {"shape": "square", "width": 64, "height": 64, "safe_margin_x": 4, "safe_margin_y": 4,
                 "size": 64, "safe_margin": 4},
        "chroma_key": {"name": "magenta", "hex": "#FF00FF", "rgb": list(MAGENTA), "selection": "fallback"},
        "states": {"idle": {"frames": frames, "fps": 4, "loop": True, "action": "idle"}},
    }


def _write_run(run_dir: Path, request: dict) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "raw").mkdir(exist_ok=True)
    (run_dir / "sprite-request.json").write_text(json.dumps(request), encoding="utf-8")


def _clean_strip(frames: int = 4) -> Image.Image:
    image = Image.new("RGB", (150 * frames + 45, 180), MAGENTA)
    draw = ImageDraw.Draw(image)
    # All four kept well outside the magenta key's fringe band (distance > 180)
    # -- a purple/pink subject color would itself trip the residue metric,
    # which is a known limitation (adaptive chroma estimation is P1, directive §8).
    colors = [(40, 200, 60), (30, 120, 220), (210, 190, 20), (60, 170, 90)]
    for index in range(frames):
        left = 35 + index * 150
        color = colors[index % len(colors)]
        draw.rectangle((left, 28, left + 82, 155), fill=color)
        draw.rectangle((left + 24, 10, left + 58, 45), fill=color)
    return image


def _malformed_strip() -> Image.Image:
    residue_a, residue_b = (200, 90, 190), (150, 90, 150)
    image = Image.new("RGB", (640, 180), MAGENTA)
    draw = ImageDraw.Draw(image)
    draw.rectangle((35, 20, 35 + 82, 160), fill=residue_a)
    draw.rectangle((215, 60, 225, 70), fill=(60, 180, 90))
    draw.rectangle((240, 90, 247, 96), fill=(60, 180, 90))
    left = 335
    draw.rectangle((left, 28, left + 82, 155), fill=(220, 40, 40))
    draw.rectangle((left + 24, 10, left + 58, 45), fill=(220, 40, 40))
    left = 485
    draw.rectangle((left + 70, 10, left + 78, 170), fill=residue_b)
    return image


# --- spritegen_bridge.normalize_state ----------------------------------------

def test_normalize_state_passes_for_a_clean_row(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    request = _sprite_request()
    _write_run(run_dir, request)
    _clean_strip().save(run_dir / "raw" / "idle.png")

    report = spritegen_bridge.normalize_state(run_dir, "idle")

    assert report["result"] == "pass"
    assert report["valid_subjects"] == 4


def test_normalize_state_raises_for_a_malformed_row(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    request = _sprite_request()
    _write_run(run_dir, request)
    _malformed_strip().save(run_dir / "raw" / "idle.png")

    with pytest.raises(spritegen_bridge.NormalizeQualityFailed) as excinfo:
        spritegen_bridge.normalize_state(run_dir, "idle")

    assert excinfo.value.report["result"] == "fail"
    assert excinfo.value.report["valid_subjects"] < 4
    assert "valid subjects" in str(excinfo.value)


def test_normalize_state_wraps_hard_failure_as_quality_failed(tmp_path: Path) -> None:
    """A hard segmentation failure (can't find `count` spans) used to escape as a
    bare SystemExit that batch_service's `except Exception` never caught
    (directive root cause). It must now surface as the same catchable type."""
    run_dir = tmp_path / "run"
    request = _sprite_request(frames=4)
    _write_run(run_dir, request)
    # A blank chroma canvas has no subjects at all -- segment_strip cannot even
    # force 4 spans out of zero content.
    Image.new("RGB", (640, 180), MAGENTA).save(run_dir / "raw" / "idle.png")

    with pytest.raises(spritegen_bridge.NormalizeQualityFailed):
        spritegen_bridge.normalize_state(run_dir, "idle")


# --- batch_service: blocks downstream on a normalize failure -----------------

def test_batch_stops_before_extract_when_normalize_fails(tmp_path: Path, monkeypatch) -> None:
    run_dir = tmp_path / "run"
    _write_run(run_dir, _sprite_request())

    extract_calls = []
    monkeypatch.setattr(spritegen_bridge, "generate_state", lambda _run, state: {"state": state})
    monkeypatch.setattr(
        spritegen_bridge, "normalize_state",
        lambda _run, state: (_ for _ in ()).throw(
            spritegen_bridge.NormalizeQualityFailed(state, {"result": "fail", "valid_subjects": 1, "expected_subjects": 4, "subjects": []})
        ),
    )
    monkeypatch.setattr(spritegen_bridge, "extract_frames", lambda *args, **kwargs: extract_calls.append(args) or 0)

    batch_service.start_batch(run_dir, ["idle"], normalize=True, refine=False, repair=False, qa=False)
    payload = {}
    for _ in range(200):
        payload = batch_service.load_queue(run_dir) or {}
        if payload.get("status") != "running":
            break
        time.sleep(0.01)

    assert payload["status"] == "failed"
    assert payload["items"][0]["status"] == "normalize_failed"
    assert "1/4" in payload["items"][0]["normalize_error"] or "1 / 4" in batch_service.status_text(run_dir)
    assert extract_calls == []  # Extract must never run against a failed normalize


# --- curate.anchor: promotion gate --------------------------------------------

def _write_normalize_report(run_dir: Path, state: str, *, result: str, subjects: list[dict] | None = None) -> None:
    report = {
        "kind": "sprite-studio-grok-row-normalization",
        "result": result,
        "expected_subjects": 4,
        "valid_subjects": 4 if result == "recovered_with_warning" else 1,
        "subjects": subjects or [],
    }
    raw = run_dir / "raw" / f"{state}.png"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.with_name(raw.stem + ".normalize.report.json").write_text(json.dumps(report), encoding="utf-8")


def test_anchor_gate_blocks_failed_normalize(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    request = _sprite_request()
    _write_normalize_report(run_dir, "idle", result="fail")

    with pytest.raises(anchor_mod.AnchorUnavailable) as excinfo:
        anchor_mod._check_normalize_quality(run_dir, request, "idle", 0)
    assert excinfo.value.kind == "normalize-failed"
    assert excinfo.value.pending is False


def test_anchor_gate_blocks_recovered_row_by_default(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    request = _sprite_request()
    _write_normalize_report(run_dir, "idle", result="recovered_with_warning")

    with pytest.raises(anchor_mod.AnchorUnavailable) as excinfo:
        anchor_mod._check_normalize_quality(run_dir, request, "idle", 0)
    assert excinfo.value.kind == "normalize-recovered"


def test_anchor_gate_allows_recovered_row_when_configured(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    request = _sprite_request()
    request["normalize_quality"] = {"anchor": {"allow_recovered": True}}
    _write_normalize_report(run_dir, "idle", result="recovered_with_warning")

    anchor_mod._check_normalize_quality(run_dir, request, "idle", 0)  # must not raise


def test_anchor_gate_blocks_invalid_selected_subject_even_when_row_recovers(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    request = _sprite_request()
    request["normalize_quality"] = {"anchor": {"allow_recovered": True}}
    _write_normalize_report(
        run_dir, "idle", result="recovered_with_warning",
        subjects=[{"index": 0, "valid": False, "reasons": ["chroma_residue_high"]}],
    )

    with pytest.raises(anchor_mod.AnchorUnavailable) as excinfo:
        anchor_mod._check_normalize_quality(run_dir, request, "idle", 0)
    assert excinfo.value.kind == "normalize-subject-invalid"


def test_anchor_gate_passes_clean_row(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    request = _sprite_request()
    _write_normalize_report(
        run_dir, "idle", result="pass",
        subjects=[{"index": index, "valid": True, "reasons": []} for index in range(4)],
    )

    anchor_mod._check_normalize_quality(run_dir, request, "idle", 0)  # must not raise


def test_anchor_gate_no_report_passes_through(tmp_path: Path) -> None:
    """No normalize report at all (e.g. a non-Grok source) is not this gate's concern."""
    run_dir = tmp_path / "run"
    request = _sprite_request()
    (run_dir / "raw").mkdir(parents=True)

    anchor_mod._check_normalize_quality(run_dir, request, "idle", 0)  # must not raise
