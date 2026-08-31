# SPDX-License-Identifier: Apache-2.0
"""Mode dispatch and engine selection for the Sprite refine stage (spec §16.4).

Drives ``refine_service.refine_state`` over a real run directory rather than
calling the engine directly, because the dispatch — which mode, which engine
version, which settings — is the part that decides what actually runs.
"""

from __future__ import annotations

import json
import pathlib

import numpy as np
import pytest
from PIL import Image

from sprite_studio.spec.layout import frames_dir_rel

from studio.backend import refine_service


CELL = 96
PITCH = 6
FRAMES = 4


def _logical(shift: int, size: int = 16) -> Image.Image:
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    pixels = image.load()
    for y in range(4, 14):
        for x in range(4, 11):
            tone = 60 + ((x * 3 + y * 5) % 4) * 35
            pixels[x, y] = (tone + 60, tone, 40, 255)
    for y in range(1, 9):
        pixels[12 + shift, y] = (230, 230, 245, 255)
    return image


def _make_run(tmp_path, *, mode: str | None = "sprite", refine: dict | None = None):
    """Build the smallest run directory the refine service can read."""
    run_dir = tmp_path / "run"
    state = "side_attack"
    frames_dir = run_dir / "frames" / "side" / "attack"
    frames_dir.mkdir(parents=True)

    files = []
    for index in range(FRAMES):
        canvas = Image.new("RGBA", (CELL, CELL), (0, 0, 0, 0))
        logical = _logical(index % 2)
        canvas.alpha_composite(
            logical.resize((logical.width * PITCH, logical.height * PITCH), Image.Resampling.NEAREST),
            (index, 2),
        )
        relative = f"frames/side/attack/frame-{index}.png"
        canvas.save(run_dir / relative)
        files.append(relative)

    request = {
        "character": {"id": "sword"},
        "cell": {"width": CELL, "height": CELL, "safe_margin_x": 4, "safe_margin_y": 4},
        "states": {state: {"frames": FRAMES, "fps": 8}},
        "directions": {"set": ["side"], "mirror": {}},
    }
    (run_dir / "sprite-request.json").write_text(json.dumps(request), encoding="utf-8")
    (run_dir / "frames" / "frames-manifest.json").write_text(
        json.dumps({"rows": [{"state": state, "files": files}]}), encoding="utf-8"
    )
    config: dict = {"locks": {"grid": "state", "palette": "character"}}
    if mode is not None:
        config["mode"] = mode
    if refine is not None:
        config["refine"] = refine
    (run_dir / "studio").mkdir(parents=True, exist_ok=True)
    (run_dir / "studio" / "studio.json").write_text(
        json.dumps({"version": 1, "kind": "sprite-studio-run", "config": config}), encoding="utf-8"
    )
    return run_dir, state


def test_refine_state_runs_the_v2_engine_by_default(tmp_path) -> None:
    run_dir, state = _make_run(tmp_path)
    result = refine_service.refine_state(run_dir, state)
    report = result.report

    assert report["kind"] == "asset-studio-sprite-refine"
    assert report["lattice"]["pitch"][0] == pytest.approx(PITCH, abs=0.2)
    assert len(result.output_files) == FRAMES
    for path in result.output_files:
        with Image.open(path) as image:
            assert image.size == (CELL, CELL)
    # The logical (true-resolution) frames are persisted too; they are the only
    # inspectable form of the result that is not already upscaled.
    # Derived, not hardcoded: the run layout is the engine's SSoT, and a literal
    # path here would test the test's guess instead of the service's behaviour.
    request = json.loads((run_dir / "sprite-request.json").read_text(encoding="utf-8"))
    logical_dir = run_dir / frames_dir_rel(request, state) / "refined" / "logical"
    assert len(list(logical_dir.glob("frame-*.png"))) == FRAMES
    assert refine_service.refine_report(run_dir, state)["kind"] == "asset-studio-sprite-refine"


def test_refine_state_never_touches_the_canonical_extraction(tmp_path) -> None:
    run_dir, state = _make_run(tmp_path)
    before = {
        path.name: path.read_bytes()
        for path in sorted((run_dir / "frames" / "side" / "attack").glob("frame-*.png"))
    }
    refine_service.refine_state(run_dir, state)
    after = {
        path.name: path.read_bytes()
        for path in sorted((run_dir / "frames" / "side" / "attack").glob("frame-*.png"))
    }
    assert before == after


def test_project_refine_overrides_reach_the_engine(tmp_path) -> None:
    run_dir, state = _make_run(tmp_path, refine={"phase_correction": "off", "palette_colors": 4})
    report = refine_service.refine_state(run_dir, state).report
    assert report["settings"]["phase"]["correction"] == "off"
    assert report["settings"]["palette"]["colors"] == 4
    assert report["shared"]["palette_colors"] <= 4


def test_engine_v1_still_produces_the_legacy_report(tmp_path) -> None:
    """Pre-split runs must reproduce; the old engine stays reachable by pin."""
    run_dir, state = _make_run(tmp_path, refine={"engine": "v1"})
    report = refine_service.refine_state(run_dir, state).report
    assert report["kind"] == "sprite-studio-frame-refine"
    assert "lattice" not in report


def test_unknown_engine_version_is_refused(tmp_path) -> None:
    run_dir, state = _make_run(tmp_path, refine={"engine": "v3"})
    with pytest.raises(ValueError, match="unknown refine engine"):
        refine_service.refine_state(run_dir, state)


def test_a_static_run_is_refused_by_the_sprite_refine_path(tmp_path) -> None:
    run_dir, state = _make_run(tmp_path, mode="static")
    assert refine_service.run_mode(run_dir) == "static"
    with pytest.raises(ValueError, match="Sprite Mode path"):
        refine_service.refine_state(run_dir, state)


def test_a_run_without_a_mode_field_loads_as_sprite(tmp_path) -> None:
    """Runs predating the split carry no mode; nothing else existed then."""
    run_dir, state = _make_run(tmp_path, mode=None)
    assert refine_service.run_mode(run_dir) == "sprite"
    assert refine_service.refine_state(run_dir, state).report["mode"] == "sprite"


def test_refine_before_extract_fails_loudly(tmp_path) -> None:
    run_dir, state = _make_run(tmp_path)
    (run_dir / "frames" / "frames-manifest.json").unlink()
    with pytest.raises(FileNotFoundError, match="extract first"):
        refine_service.refine_state(run_dir, state)


def test_refine_is_reproducible_across_calls(tmp_path) -> None:
    run_dir, state = _make_run(tmp_path)
    first = [Image.open(path).convert("RGBA") for path in refine_service.refine_state(run_dir, state).output_files]
    first_arrays = [np.asarray(image).copy() for image in first]
    second = [Image.open(path).convert("RGBA") for path in refine_service.refine_state(run_dir, state).output_files]
    for left, right in zip(first_arrays, second):
        assert np.array_equal(left, np.asarray(right))


def test_engine_v1_output_is_byte_identical_to_calling_the_legacy_refiner(tmp_path) -> None:
    """The v1 pin is only worth having if it actually reproduces.

    Asserts the bytes, not the routing: a report kind proves which function ran,
    not that the arguments derived around it stayed the same.
    """
    from studio.core.refine.frame_refiner import refine_files

    run_dir, state = _make_run(tmp_path, refine={"engine": "v1"})
    service_files = refine_service.refine_state(run_dir, state).output_files
    service_bytes = [pathlib.Path(path).read_bytes() for path in service_files]

    request = json.loads((run_dir / "sprite-request.json").read_text(encoding="utf-8"))
    manifest = json.loads((run_dir / "frames" / "frames-manifest.json").read_text(encoding="utf-8"))
    row = manifest["rows"][0]
    cell = request["cell"]
    direct = refine_files(
        [run_dir / row["files"][index] for index in range(len(row["files"]))],
        tmp_path / "direct",
        state=state,
        cell_width=int(cell["width"]),
        cell_height=int(cell["height"]),
        safe_margin_x=int(cell["safe_margin_x"]),
        safe_margin_y=int(cell["safe_margin_y"]),
        locks={"grid": "state", "palette": "character"},
        palette_colors=16,
        logical_height=None,
    )
    direct_bytes = [pathlib.Path(path).read_bytes() for path in direct.output_files]
    assert service_bytes == direct_bytes
