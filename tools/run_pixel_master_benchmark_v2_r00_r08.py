#!/usr/bin/env python3
"""Run the corrected Tier B-only R00-R08 Phase 2A benchmark."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import pixel_master_benchmark_v2 as preparation  # noqa: E402
from tools import pixel_master_benchmark_v2_execute as executor  # noqa: E402


DEFAULT_CONFIG = ROOT / "benchmark_v2" / "configs" / "benchmark_matrix_r00_r08.json"
DEFAULT_MANIFEST = ROOT / "benchmark_v2" / "configs" / "tier_b_fixtures_r00_r08.json"
DEFAULT_SOURCE_ROOT = ROOT / "benchmark_v2" / "sources" / "tier_b"
DEFAULT_OUT = ROOT / "benchmark_v2" / "phase2A_r00_r08"
DEFAULT_AI_INPUT_ROOT = ROOT / "benchmark_v2" / "ai_inputs"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--ai-input-root", type=Path, default=DEFAULT_AI_INPUT_ROOT)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_root = args.out if args.out.is_absolute() else ROOT / args.out
    ai_input_root = args.ai_input_root if args.ai_input_root.is_absolute() else ROOT / args.ai_input_root
    context = preparation.prepare_run(
        config_path=DEFAULT_CONFIG,
        output_root=output_root,
        methods=("A1", "A2", "B1", "C1", "C2"),
        tier_a_sources=(),
        tier_b_sources=("R00", "R01", "R02", "R03", "R04", "R05", "R06", "R07", "R08"),
        manifest_path=DEFAULT_MANIFEST,
        tier_b_root=DEFAULT_SOURCE_ROOT,
    )
    rows = executor.run_phase_2a(
        context,
        output_root=output_root,
        ai_input_root=ai_input_root,
        force=args.force,
    )
    print(f"phase2A corrected R00-R08 complete: {len(rows)} raw/post records")
    print(f"summary: {output_root / 'reports' / 'benchmark_summary.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
