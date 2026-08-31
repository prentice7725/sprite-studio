# SPDX-License-Identifier: Apache-2.0
"""Provider-neutral contract for optional masked AI micro repair."""

from __future__ import annotations

from typing import Protocol

from PIL import Image


class AiMicroFixProvider(Protocol):
    def repair_masked(self, frame: Image.Image, mask: Image.Image, instruction: str,
                      *, palette: tuple[tuple[int, int, int, int], ...]) -> Image.Image:
        """Modify only the mask; callers must re-lock and diff-check the result."""


def validate_micro_fix(before: Image.Image, after: Image.Image, mask: Image.Image,
                       palette: set[tuple[int, int, int, int]]) -> None:
    if before.size != after.size or mask.size != before.size:
        raise ValueError("AI micro fix must preserve the frame and mask dimensions")
    before = before.convert("RGBA")
    after = after.convert("RGBA")
    mask = mask.convert("L")
    for y in range(before.height):
        for x in range(before.width):
            old = before.getpixel((x, y))
            new = after.getpixel((x, y))
            if mask.getpixel((x, y)) == 0 and old != new:
                raise ValueError("AI micro fix changed an unmasked pixel")
            if new[3] > 0 and new not in palette:
                raise ValueError("AI micro fix introduced a color outside the shared palette")


def normalize_and_validate_micro_fix(before: Image.Image, after: Image.Image, mask: Image.Image,
                                     palette: set[tuple[int, int, int, int]]) -> Image.Image:
    """Re-lock an imported logical result before it can enter repaired outputs."""
    normalized = after.convert("RGBA").copy()
    pixels = normalized.load()
    for y in range(normalized.height):
        for x in range(normalized.width):
            color = pixels[x, y]
            if color[3] not in {0, 255}:
                raise ValueError("AI micro fix introduced soft alpha")
            if color[3] == 0:
                pixels[x, y] = (0, 0, 0, 0)
    validate_micro_fix(before, normalized, mask, palette)
    return normalized
