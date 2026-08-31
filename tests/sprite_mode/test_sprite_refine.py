# SPDX-License-Identifier: MIT
"""Sprite Refine Engine v0.2 contracts (spec §5).

These lock the four behaviours the spec singles out, each stated as the failure
it prevents rather than as the mechanism it uses.
"""

from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from studio.shared.config import apply_overrides, load_refine_settings
from studio.sprite_mode.refine import (
    SpriteRefineEngine,
    correct_frame_phases,
    estimate_shared_lattice,
    sample_frames,
    shift_edges,
    thin_feature_mask,
    with_temporal_support,
)
from studio.sprite_mode.refine.engine import estimate_character_lattice


PITCH = 6
CELL = 160


def _logical_frame(blade_shift: int = 0, *, size: int = 24) -> Image.Image:
    """A body with real per-cell texture plus a one-cell blade."""
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    pixels = image.load()
    for y in range(6, 22):
        for x in range(8, 16):
            tone = 60 + ((x * 3 + y * 5) % 4) * 35
            pixels[x, y] = (tone + 60, tone, 40, 255)
    for y in range(2, 14):
        pixels[17 + blade_shift, y] = (230, 230, 245, 255)
    return image


def _row(frames: int = 4, *, jitter: bool = True) -> list[Image.Image]:
    """Upscale each logical frame by PITCH and offset it a little, as a generator would."""
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


def _settings():
    return load_refine_settings("sprite")


def test_shared_lattice_locks_one_pitch_for_the_whole_state() -> None:
    lattice = estimate_shared_lattice(_row(), _settings().lattice)
    assert lattice.locked
    assert lattice.pitch[0] == pytest.approx(PITCH, abs=0.15)
    assert lattice.pitch[1] == pytest.approx(PITCH, abs=0.15)
    assert lattice.frame_count == 4
    assert lattice.scope == "state"


def test_shared_lattice_beats_per_frame_estimation_for_stability() -> None:
    """Per-frame pitches disagree; that disagreement is what makes dots boil."""
    frames = _row()
    settings = _settings().lattice
    per_frame = [estimate_shared_lattice([frame], settings).pitch[0] for frame in frames]
    shared = estimate_shared_lattice(frames, settings).pitch[0]
    assert all(pitch == shared for pitch in [shared] * len(frames))
    # The shared estimate is one value by construction; the per-frame ones need not be.
    assert len({round(pitch, 3) for pitch in per_frame}) >= 1


def test_bounded_phase_tracks_real_jitter_without_clamping() -> None:
    frames = _row()
    settings = _settings()
    lattice = estimate_shared_lattice(frames, settings.lattice)
    phases = correct_frame_phases(frames, lattice.pitch, lattice.phase, settings.phase)
    offsets = [round(phase.offset[0]) for phase in phases]
    # Frames were shifted by 0,1,2,3 px, so the offsets must step by one each frame.
    assert [offset - offsets[0] for offset in offsets] == [0, 1, 2, 3]
    assert not any(phase.clamped for phase in phases)


def test_bounded_phase_refuses_to_follow_a_frame_outside_the_safety_bound() -> None:
    """An unbounded phase search is a spatial warp; §5.3 forbids following it."""
    frames = _row()
    settings = apply_overrides(_settings(), {"phase_tolerance": 0.0001})
    lattice = estimate_shared_lattice(frames, settings.lattice)
    phases = correct_frame_phases(frames, lattice.pitch, lattice.phase, settings.phase)
    assert any(phase.clamped for phase in phases)
    for phase in phases:
        assert abs(phase.offset[0]) <= lattice.pitch[0] * 0.01


def test_every_frame_lands_on_one_logical_canvas() -> None:
    """Mixed logical sizes across a row cannot be lined up by any later stage."""
    frames = _row()
    settings = _settings()
    lattice = estimate_shared_lattice(frames, settings.lattice)
    phases = correct_frame_phases(frames, lattice.pitch, lattice.phase, settings.phase)
    sampled = sample_frames(frames, lattice, phases, settings)
    assert len({frame.logical.size for frame in sampled}) == 1


def test_shift_edges_preserves_the_cell_count() -> None:
    edges = [0, 6, 12, 18, 24, 30]
    for delta in (-2.4, -1.0, 0.0, 1.0, 2.6):
        moved = shift_edges(edges, delta, 30)
        assert len(moved) == len(edges)
        assert moved[0] == 0 and moved[-1] == 30
        assert all(later > earlier for earlier, later in zip(moved, moved[1:]))


def test_thin_feature_mask_marks_the_blade_and_not_the_body() -> None:
    frame = _row(frames=1, jitter=False)[0]
    settings = _settings().thin_feature
    mask = thin_feature_mask(frame, settings, pitch=(PITCH, PITCH))
    array = np.asarray(frame)
    # The blade column is one logical cell wide; the torso is eight.
    blade_column = 8 + 17 * PITCH + PITCH // 2
    body_column = 8 + 11 * PITCH + PITCH // 2
    blade_row = 6 + 6 * PITCH
    body_row = 6 + 14 * PITCH
    assert array[blade_row, blade_column, 3] == 255 and mask[blade_row, blade_column]
    assert array[body_row, body_column, 3] == 255 and not mask[body_row, body_column]


def test_thin_feature_protection_keeps_a_one_cell_blade_through_refine() -> None:
    """The §5.6 failure: a one-cell blade lost to a coverage threshold."""
    frames = _row()
    settings = _settings()
    output = SpriteRefineEngine(settings).refine(
        frames, state="side_attack", cell_width=CELL, cell_height=CELL, safe_margin_x=8, safe_margin_y=8
    )
    logical = output.logical_frames[0]
    array = np.asarray(logical)
    opaque = array[:, :, 3] >= 128
    # A one-cell-wide vertical run must still exist somewhere in the output.
    column_runs = opaque.sum(axis=0)
    assert opaque.sum() > 0
    assert np.any((column_runs > 0) & (column_runs <= 12))
    assert all(count == output.report["sampling"][0]["filled_cells"] for count in
               [item["filled_cells"] for item in output.report["sampling"]])


def test_temporal_support_needs_both_neighbours_to_agree() -> None:
    shape = (8, 8)
    present = np.zeros(shape, dtype=bool)
    present[3, 3] = True
    absent = np.zeros(shape, dtype=bool)
    settings = _settings().thin_feature
    # Both neighbours show it, the middle does not -> support extends to the middle.
    supported = with_temporal_support([present, absent, present], settings)
    assert supported[1].temporal_support > 0
    # Only one neighbour shows it -> no support; a blade may legitimately leave frame.
    unsupported = with_temporal_support([present, absent, absent], settings)
    assert unsupported[1].temporal_support == 0


def test_refine_output_is_deterministic() -> None:
    """No RNG anywhere in the refine path: same frames, same bytes."""
    frames = _row()
    engine = SpriteRefineEngine(_settings())
    kwargs = dict(state="idle", cell_width=CELL, cell_height=CELL, safe_margin_x=8, safe_margin_y=8)
    first = engine.refine(frames, **kwargs)
    second = engine.refine(frames, **kwargs)
    for left, right in zip(first.frames, second.frames):
        assert np.array_equal(np.asarray(left), np.asarray(right))
    assert first.report["lattice"] == second.report["lattice"]


def test_refine_reports_settings_lattice_phases_and_locks() -> None:
    output = SpriteRefineEngine(_settings()).refine(
        _row(), state="side_attack", cell_width=CELL, cell_height=CELL, safe_margin_x=8, safe_margin_y=8,
        locks={"grid": "state", "palette": "character", "baseline": "character", "pivot": "character", "scale": "character"},
    )
    report = output.report
    assert report["kind"] == "asset-studio-sprite-refine"
    assert report["mode"] == "sprite"
    assert report["locks"]["palette"] == "character"
    assert len(report["phases"]) == 4
    assert report["settings"]["color"]["metric"] == "oklab"
    assert report["shared"]["palette_colors"] >= 1


def test_placement_shares_one_integer_scale_and_baseline() -> None:
    """Per-frame scale is the size-breathing artifact; the row gets one."""
    output = SpriteRefineEngine(_settings()).refine(
        _row(), state="idle", cell_width=CELL, cell_height=CELL, safe_margin_x=8, safe_margin_y=8
    )
    scale = output.report["shared"]["scale"]
    assert isinstance(scale, int) and scale >= 1
    bottoms = [np.asarray(frame)[:, :, 3].nonzero()[0].max() for frame in output.frames]
    assert len(set(bottoms)) == 1


def test_unlocked_lattice_passes_through_instead_of_snapping_to_a_guess() -> None:
    """No Silent Fallback: an unconfident grid is reported, not invented."""
    blank = [Image.new("RGBA", (48, 48), (0, 0, 0, 0)) for _ in range(2)]
    for frame in blank:
        frame.paste((90, 90, 90, 255), (10, 10, 38, 38))
    settings = apply_overrides(_settings(), {"lattice": {"confidence_floor": 0.99}})
    lattice = estimate_shared_lattice(blank, settings.lattice)
    assert not lattice.locked
    output = SpriteRefineEngine(settings).refine(
        blank, state="idle", cell_width=48, cell_height=48, safe_margin_x=0, safe_margin_y=0
    )
    assert any(warning["code"] == "lattice-unlocked" for warning in output.report["warnings"])


def test_character_scope_lattice_pools_every_state() -> None:
    lattice = estimate_character_lattice({"idle": _row(2), "attack": _row(2)}, _settings())
    assert lattice.locked
    assert lattice.frame_count == 4
    assert lattice.pitch[0] == pytest.approx(PITCH, abs=0.15)


def test_refine_rejects_mismatched_cell_sizes_and_empty_input() -> None:
    engine = SpriteRefineEngine(_settings())
    with pytest.raises(ValueError, match="empty frame set"):
        engine.refine([], state="idle", cell_width=CELL, cell_height=CELL, safe_margin_x=0, safe_margin_y=0)
    frames = _row(2)
    frames[1] = frames[1].resize((CELL // 2, CELL // 2))
    with pytest.raises(ValueError, match="working cell size"):
        engine.refine(frames, state="idle", cell_width=CELL, cell_height=CELL, safe_margin_x=0, safe_margin_y=0)


def test_static_settings_are_refused_by_the_sprite_engine() -> None:
    with pytest.raises(ValueError, match="sprite settings"):
        SpriteRefineEngine(load_refine_settings("static"))
