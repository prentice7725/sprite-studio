# SPDX-License-Identifier: Apache-2.0
"""Test character-scoped shared lattice estimation across multiple animation states."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from studio.backend.refine_service import estimate_run_character_lattice, refine_states


PITCH = 6
CELL = 160


def _logical_frame(blade_shift: int = 0, *, size: int = 24) -> Image.Image:
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    pixels = image.load()
    for y in range(6, 22):
        for x in range(8, 16):
            tone = 60 + ((x * 3 + y * 5) % 4) * 35
            pixels[x, y] = (tone + 60, tone, 40, 255)
    for y in range(2, 14):
        pixels[17 + blade_shift, y] = (230, 230, 245, 255)
    return image


def _row(frames: int = 2, *, jitter: bool = True) -> list[Image.Image]:
    row: list[Image.Image] = []
    for index in range(frames):
        canvas = Image.new("RGBA", (CELL, CELL), (0, 0, 0, 0))
        logical = _logical_frame(index % 2)
        canvas.alpha_composite(
            logical.resize((logical.width * PITCH, logical.height * PITCH), Image.Resampling.NEAREST),
            (8 + (index if jitter else 0), 6),
        )
        row.append(canvas)
    return row


def test_character_lattice_service(tmp_path: Path):
    run_dir = tmp_path / "test_run"
    run_dir.mkdir(parents=True, exist_ok=True)
    
    # Create studio metadata
    studio_dir = run_dir / "studio"
    studio_dir.mkdir(parents=True, exist_ok=True)
    studio_meta = {
        "kind": "sprite-studio-run",
        "version": 1,
        "config": {
            "mode": "sprite",
            "refine": {
                "shared_lattice_scope": "character",
                "phase_correction": "bounded",
            }
        }
    }
    (studio_dir / "studio.json").write_text(json.dumps(studio_meta), encoding="utf-8")
    
    # Create sprite-request.json
    request_data = {
        "cell": {"width": CELL, "height": CELL, "safe_margin": 16},
        "states": {"side_idle": {}, "side_walk": {}},
    }
    (run_dir / "sprite-request.json").write_text(json.dumps(request_data), encoding="utf-8")
    
    # Create frames manifest and dummy frames
    frames_dir = run_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    
    idle_dir = frames_dir / "side_idle"
    idle_dir.mkdir(parents=True, exist_ok=True)
    walk_dir = frames_dir / "side_walk"
    walk_dir.mkdir(parents=True, exist_ok=True)
    
    idle_frames = _row(2)
    walk_frames = _row(2)
    
    idle_frames[0].save(idle_dir / "frame-00.png")
    idle_frames[1].save(idle_dir / "frame-01.png")
    walk_frames[0].save(walk_dir / "frame-00.png")
    walk_frames[1].save(walk_dir / "frame-01.png")
    
    manifest = {
        "kind": "sprite-studio-frames-manifest",
        "rows": [
            {"state": "side_idle", "dir": "frames/side_idle", "files": ["frames/side_idle/frame-00.png", "frames/side_idle/frame-01.png"]},
            {"state": "side_walk", "dir": "frames/side_walk", "files": ["frames/side_walk/frame-00.png", "frames/side_walk/frame-01.png"]},
        ]
    }
    (frames_dir / "frames-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    
    # Test estimate_run_character_lattice
    shared = estimate_run_character_lattice(run_dir, states=["side_idle", "side_walk"])
    assert shared.pitch[0] == pytest.approx(PITCH, abs=0.15)
    assert shared.pitch[1] == pytest.approx(PITCH, abs=0.15)
    assert shared.locked is True
    
    # Test refine_states with character scope
    results = refine_states(run_dir, ["side_idle", "side_walk"])
    assert "side_idle" in results
    assert "side_walk" in results
    
    # Check that refine reports recorded character scope
    report_idle = results["side_idle"].report
    assert report_idle["lattice"]["scope"] == "character"
    assert report_idle["lattice"]["pitch"][0] == pytest.approx(PITCH, abs=0.15)
    
    report_walk = results["side_walk"].report
    assert report_walk["lattice"]["scope"] == "character"
    assert report_walk["lattice"]["pitch"][0] == pytest.approx(PITCH, abs=0.15)
