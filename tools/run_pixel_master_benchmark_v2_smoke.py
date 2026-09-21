#!/usr/bin/env python3
"""Run the gated Phase 2A logical-grid smoke benchmark only."""

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
DEFAULT_OUT = ROOT / "benchmark_v2" / "phase2A_rebench_128logical" / "smoke"
DEFAULT_AI_INPUT_ROOT = ROOT / "benchmark_v2" / "ai_inputs"
SMOKE_SOURCES = ("R00", "R03", "R06")


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
        tier_b_sources=SMOKE_SOURCES,
        manifest_path=DEFAULT_MANIFEST,
        tier_b_root=DEFAULT_SOURCE_ROOT,
    )
    rows = executor.run_phase_2a(
        context,
        output_root=output_root,
        ai_input_root=ai_input_root,
        force=args.force,
    )
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    print(f"phase2A logical smoke complete: {len(rows)} method results")
    print("status:", ", ".join(f"{key}={value}" for key, value in sorted(counts.items())))
    print(f"summary: {output_root / 'reports' / 'smoke_summary.md'}")
    ai_failures = [
        row for row in rows
        if row["method_id"] in {"C1", "C2"} and row["status"] != "PASS"
    ]
    if ai_failures:
        print(
            "STOP: C1/C2 smoke gate did not pass; resolve provenance/logical-grid failures "
            "before running the full R00-R08 benchmark."
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
