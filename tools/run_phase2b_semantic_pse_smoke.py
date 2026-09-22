#!/usr/bin/env python3
"""Run the R00/R03/R06 Phase 2B semantic PSE smoke benchmark."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import pixel_master_benchmark_phase2b_execute as executor  # noqa: E402
from tools import pixel_master_benchmark_v2 as preparation  # noqa: E402


DEFAULT_CONFIG = ROOT / "benchmark_v2" / "configs" / "benchmark_matrix_r00_r08.json"
DEFAULT_MANIFEST = ROOT / "benchmark_v2" / "configs" / "tier_b_fixtures_r00_r08.json"
DEFAULT_SOURCE_ROOT = ROOT / "benchmark_v2" / "sources" / "tier_b"
DEFAULT_OUT = ROOT / "benchmark_v2" / "phase2B_semantic_pse" / "smoke"
SMOKE_SOURCES = ("R00", "R03", "R06")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--provider", choices=("grok", "codex"), default="grok")
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_root = args.out if args.out.is_absolute() else ROOT / args.out
    context = preparation.prepare_run(
        config_path=DEFAULT_CONFIG,
        output_root=output_root,
        methods=("A1", "A2", "B1"),
        tier_a_sources=(),
        tier_b_sources=SMOKE_SOURCES,
        manifest_path=DEFAULT_MANIFEST,
        tier_b_root=DEFAULT_SOURCE_ROOT,
    )
    rows = executor.run_phase_2b(context, output_root=output_root, provider=args.provider, force=args.force)
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    print(f"phase2B semantic PSE smoke complete: {len(rows)} method results")
    print("status:", ", ".join(f"{key}={value}" for key, value in sorted(counts.items())))
    print(f"summary: {output_root / 'reports' / 'smoke_summary.md'}")
    d_failures = [row for row in rows if row["method_id"] in {"D1", "D2"} and row["status"] != "PASS_LOGICAL_MASTER"]
    if d_failures:
        print("STOP: D1/D2 smoke did not produce six validated logical masters before full Phase 2B.")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
