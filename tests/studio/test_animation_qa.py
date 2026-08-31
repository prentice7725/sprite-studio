# SPDX-License-Identifier: MIT
"""Animation QA and runtime export contracts."""

from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace

from PIL import Image, ImageDraw

from studio.backend.export_service import build_runtime
from studio.backend import batch_service, spritegen_bridge
from studio.backend.history_service import summary as history_summary
from studio.core.animation import analyze_animation


def _frame(box: tuple[int, int, int, int], *, size: int = 96) -> Image.Image:
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(image).rectangle(box, fill=(80, 100, 190, 255))
    return image


def test_animation_qa_detects_continuity_problems() -> None:
    frames = [_frame((8, 20, 28, 79)), _frame((66, 24, 86, 83)), _frame((66, 24, 86, 83)), _frame((8, 20, 28, 79))]
    result = analyze_animation(frames, "side_attack")
    codes = {warning["code"] for warning in result.warnings}

    assert {"BASELINE_JITTER", "DUPLICATE_FRAME", "HANDEDNESS_FLIP"} <= codes
    assert result.metrics["frame_count"] == 4


def test_runtime_export_resizes_atlas_and_manifest(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    atlas = Image.new("RGBA", (192, 96), (0, 0, 0, 0))
    ImageDraw.Draw(atlas).rectangle((8, 8, 40, 80), fill=(255, 255, 255, 255))
    atlas.save(run_dir / "sprite-sheet-alpha.png")
    manifest = {
        "cell": {"width": 96, "height": 96, "size": 96},
        "sprite_sheet_alpha": "sprite-sheet-alpha.png",
        "animation": {"cellWidth": 96, "cellHeight": 96, "rows": {"side_idle": {"frames": 2}}},
        "frame_layout": {"sheetWidth": 192, "sheetHeight": 96, "cellWidth": 96, "cellHeight": 96,
                         "rows": {"side_idle": [{"x": 0, "y": 0, "w": 96, "h": 96}, {"x": 96, "y": 0, "w": 96, "h": 96}]}},
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    result = build_runtime(run_dir, runtime_size=48)

    assert result["size"] == (96, 48)
    with Image.open(result["atlas"]) as runtime:
        assert runtime.size == (96, 48)
    runtime_manifest = json.loads(result["manifest"].read_text(encoding="utf-8"))
    assert runtime_manifest["cell"]["width"] == 48
    assert runtime_manifest["animation"]["cellHeight"] == 48
    assert runtime_manifest["frame_layout"]["rows"]["side_idle"][1]["x"] == 48


def test_batch_queue_runs_selected_states_and_persists_status(tmp_path: Path, monkeypatch) -> None:
    run_dir = tmp_path / "run"
    (run_dir / "studio").mkdir(parents=True)
    (run_dir / "sprite-request.json").write_text(json.dumps({"states": {"side_idle": {}, "side_attack": {}}}), encoding="utf-8")
    monkeypatch.setattr(spritegen_bridge, "generate_state", lambda _run, state: {"state": state, "provider": "test"})
    monkeypatch.setattr(spritegen_bridge, "normalize_state", lambda _run, state: {"state": state})
    monkeypatch.setattr(spritegen_bridge, "extract_frames", lambda *_args: 0)
    monkeypatch.setattr(spritegen_bridge, "refine_frames", lambda _run, state: SimpleNamespace(report={"state": state}))
    monkeypatch.setattr(spritegen_bridge, "animation_qa", lambda _run, state: SimpleNamespace(to_dict=lambda: {"state": state, "warnings": []}))

    job_id = batch_service.start_batch(run_dir, ["side_attack"], normalize=True, refine=True, qa=True)
    for _ in range(50):
        payload = batch_service.load_queue(run_dir) or {}
        if payload.get("status") != "running":
            break
        time.sleep(0.01)

    assert payload["job_id"] == job_id
    assert payload["status"] == "complete"
    assert payload["items"][0]["status"] == "complete"


def test_history_summary_reads_generation_attempts_and_takes(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    history_dir = run_dir / "studio" / "history" / "side_attack"
    history_dir.mkdir(parents=True)
    (history_dir / "attempt-20260829T000000Z.json").write_text(json.dumps({"timestamp": "20260829T000000Z", "provider": "grok"}), encoding="utf-8")
    (run_dir / "sprite-request.json").write_text(json.dumps({"states": {"side_attack": {"takes": [{"label": "reroll1", "frames": 4}]}}}), encoding="utf-8")
    take_dir = run_dir / "raw" / "side_attack.takes"
    take_dir.mkdir(parents=True)
    (take_dir / "reroll1.png").write_bytes(b"take")

    text = history_summary(run_dir, "side_attack")

    assert "generation attempts: **1**" in text
    assert "`reroll1`" in text
    assert "Latest attempt" in text
