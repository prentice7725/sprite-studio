# SPDX-License-Identifier: Apache-2.0
"""Standalone Pixelize M1 CLI.

Usage:
    python -m sprite_studio.pixelize INPUT --size 128 --palette 32 --out-dir out

The main ``sprite-studio`` command registry can absorb this subcommand later;
keeping the M1 entrypoint standalone avoids coupling the image algorithm to the
large legacy command table while the feature is still being validated.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from studio.static_mode.pixelize import PixelizeOptions, pixelize_file


def _palette(value: str) -> int | None:
    if value.lower() == "auto":
        return None
    parsed = int(value)
    if parsed not in {16, 24, 32, 48}:
        raise argparse.ArgumentTypeError("palette must be auto, 16, 24, 32, or 48")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Convert a smooth illustration into a deterministic logical pixel master.")
    parser.add_argument("input", type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--stem", default="master_pixel")
    parser.add_argument("--size", type=int, choices=(128, 160, 192, 256), default=128)
    parser.add_argument("--palette", type=_palette, default=32)
    parser.add_argument("--dither", choices=("none", "ordered-low", "ordered"), default="none")
    parser.add_argument("--background", choices=("keep", "cleanup"), default="keep")
    parser.add_argument("--outline", choices=("preserve", "auto"), default="preserve")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = pixelize_file(
        args.input,
        args.out_dir,
        PixelizeOptions(
            target_size=args.size,
            palette_size=args.palette,
            dither=args.dither,
            background=args.background,
            outline=args.outline,
        ),
        stem=args.stem,
    )
    print(f"pixelized: {result.output_path}")
    print(f"logical size: {result.logical_size[0]}x{result.logical_size[1]}")
    print(f"palette: {len(result.palette)} colors -> {result.palette_path}")
    print(f"profile: {result.profile_path}")
    print(f"report: {result.report_path}")
    if result.warnings:
        for warning in result.warnings:
            print(f"warning [{warning.get('code', 'pixelize')}]: {warning.get('message', warning)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
