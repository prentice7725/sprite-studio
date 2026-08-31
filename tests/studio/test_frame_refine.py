# SPDX-License-Identifier: Apache-2.0
"""Frame Refine and shared character lock contracts."""

from __future__ import annotations

from PIL import Image, ImageDraw

from studio.core.refine import FrameRefiner


def _frame(width: int, height: int, box: tuple[int, int, int, int], color: tuple[int, int, int]) -> Image.Image:
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    ImageDraw.Draw(image).rectangle(box, fill=(*color, 255))
    return image


def test_refine_uses_shared_scale_baseline_grid_and_palette() -> None:
    frames = [
        _frame(96, 96, (30, 20, 66, 84), (70, 90, 180)),
        _frame(96, 96, (22, 28, 72, 84), (80, 100, 190)),
    ]

    refined, report = FrameRefiner().refine(
        frames,
        cell_width=96,
        cell_height=96,
        safe_margin_x=8,
        safe_margin_y=8,
        state="side_attack",
        locks={"grid": "state", "palette": "character", "baseline": "character", "pivot": "character", "scale": "character"},
        palette_colors=16,
        logical_height=48,
    )

    assert [frame.size for frame in refined] == [(96, 96), (96, 96)]
    assert report["locks"]["palette"] == "character"
    assert report["shared"]["grid_scale"] == 2
    assert report["shared"]["baseline_y"] == 88
    bottoms = [frame.getchannel("A").getbbox()[3] for frame in refined]
    assert bottoms == [88, 88]
