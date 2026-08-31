# SPDX-License-Identifier: MIT
"""Deprecated shim — image generation now lives in `sprite_studio.gen`.

This module previously stood in as a desktop-only placeholder during the package
split. Provider-backed generation (codex `image_gen`, grok Imagine) is now a
first-class engine module: `sprite_studio.gen` / CLI `sprite-studio gen`. Keeping two
generation surfaces would violate SSoT, so this shim redirects and fails loudly
if called directly.
"""

from __future__ import annotations


def run(**_kwargs: object) -> int:
    raise SystemExit(
        "sprite_studio.gen.generate_image is retired — use `sprite_studio.gen` "
        "(CLI: `sprite-studio gen --provider codex|grok --prompt ... --out ...`)"
    )
