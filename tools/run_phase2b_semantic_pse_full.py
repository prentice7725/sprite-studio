#!/usr/bin/env python3
"""Run the Phase 2B full R00-R08 semantic PSE benchmark once."""

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
DEFAULT_OUT = ROOT / "benchmark_v2" / "phase2B_semantic_pse" / "full_r00_r08"
FULL_SOURCES = tuple(f"R{index:02d}" for index in range(9))


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
        tier_b_sources=FULL_SOURCES,
        manifest_path=DEFAULT_MANIFEST,
        tier_b_root=DEFAULT_SOURCE_ROOT,
    )
    rows = executor.run_phase_2b(
        context,
        output_root=output_root,
        provider=args.provider,
        force=args.force,
        run_label="Full R00–R08",
    )
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    d1 = [row for row in rows if row["method_id"] == "D1"]
    d2 = [row for row in rows if row["method_id"] == "D2"]
    print(f"phase2B full R00-R08 complete: {len(rows)} method results")
    print("status:", ", ".join(f"{key}={value}" for key, value in sorted(counts.items())))
    print(f"D1 logical masters: {sum(row['status'] == 'PASS_LOGICAL_MASTER' for row in d1)}/{len(d1)}")
    print(f"D2 logical masters: {sum(row['status'] == 'PASS_LOGICAL_MASTER' for row in d2)}/{len(d2)}")
    print(f"summary: {output_root / 'reports' / 'benchmark_summary.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
