# SPDX-License-Identifier: MIT
"""Repair adoption is explicit, revision-pinned and consumed by compose/export."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from PIL import Image

from conftest import run_script
from sprite_studio.curate.curation import frame_variant, load_curation
from sprite_studio.spec.layout import frames_dir_rel, row_frame_rel
from sprite_studio.serve.serve_curation import build_run_state
from studio.backend.repair_service import adopt_repaired, unadopt_repaired


def _revision(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()[:24]


def test_adopted_repaired_frames_are_baked_and_stale_bytes_fail_loud(fixture_run_dir: Path) -> None:
    run = fixture_run_dir
    extracted = run_script("extract_sprite_row_frames.py", "--run-dir", str(run))
    assert extracted.returncode == 0, extracted.stdout + extracted.stderr
    request = json.loads((run / "sprite-request.json").read_text(encoding="utf-8"))
    manifest = json.loads((run / "frames" / "frames-manifest.json").read_text(encoding="utf-8"))
    state = next(iter(request["states"]))
    row = next(item for item in manifest["rows"] if item["state"] == state)
    state_dir = run / frames_dir_rel(request, state)
    refined_dir = state_dir / "refined"
    repaired_dir = state_dir / "repaired"
    repair_dir = state_dir / "repair"
    refined_dir.mkdir(parents=True)
    repaired_dir.mkdir(parents=True)
    repair_dir.mkdir(parents=True)
    cell = request["cell"]
    size = (int(cell.get("width", cell.get("size"))), int(cell.get("height", cell.get("size"))))
    marker = (21, 201, 111, 255)
    refined: list[Path] = []
    repaired: list[Path] = []
    for index in range(len(row["files"])):
        source = run / row_frame_rel(row, index)
        refined_path = refined_dir / f"frame-{index}.png"
        repaired_path = repaired_dir / f"frame-{index}.png"
        refined_path.write_bytes(source.read_bytes())
        Image.new("RGBA", size, marker).save(repaired_path)
        refined.append(refined_path)
        repaired.append(repaired_path)
    log = {
        "kind": "sprite-studio-repair-log",
        "state": state,
        "source_revision": _revision(refined),
        "source_files": [path.relative_to(run).as_posix() for path in refined],
        "output_revision": _revision(repaired),
        "output_files": [path.relative_to(run).as_posix() for path in repaired],
        "changes": [],
    }
    (repair_dir / "repair.log.json").write_text(json.dumps(log), encoding="utf-8")

    adopted = adopt_repaired(run, state)
    assert adopted["output_revision"] == log["output_revision"]
    assert frame_variant(load_curation(run), state) == "repaired"
    served = build_run_state(run)
    served_state = next(item for item in served["states"] if item["name"] == state)
    assert served_state["frames"][0]["repairedUrl"].endswith("/repaired/frame-0.png")

    composed = run_script("compose_sprite_atlas.py", "--run-dir", str(run))
    assert composed.returncode == 0, composed.stdout + composed.stderr
    baked_manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    assert baked_manifest["animation"]["rows"][state]["frame_variant"] == "repaired"
    row_index = list(request["states"]).index(state)
    with Image.open(run / "sprite-sheet-alpha.png") as atlas:
        assert atlas.convert("RGBA").getpixel((size[0] // 2, row_index * size[1] + size[1] // 2)) == marker

    refined_bytes = refined[0].read_bytes()
    Image.new("RGBA", size, (0, 0, 255, 255)).save(refined[0])
    with pytest.raises(SystemExit, match="repaired source frames changed"):
        load_curation(run)
    refined[0].write_bytes(refined_bytes)

    Image.new("RGBA", size, (255, 0, 0, 255)).save(repaired[0])
    with pytest.raises(SystemExit, match="repaired output bytes changed"):
        load_curation(run)

    unadopt_repaired(run, state)
    assert frame_variant(load_curation(run), state) == "pixel"
