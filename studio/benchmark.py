# SPDX-License-Identifier: Apache-2.0
"""Runnable synthetic-degradation benchmark (spec §9, §16.10).

    python -m studio.benchmark --out runs/benchmark/baseline.json
    python -m studio.benchmark --baseline runs/benchmark/baseline.json

Spec §16.10 says algorithm changes must not regress past the benchmark. A
benchmark that can only be called from a test is not a gate anyone will use
before changing a threshold, so it gets a command: record a baseline once, then
compare every later run against it. The comparison exits non-zero when any case
regressed, which is what makes it usable in CI.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from studio.shared.benchmark import compare_runs, default_cases, run_benchmark
from studio.shared.benchmark.degrade import catalogue


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, help="write the report JSON here")
    parser.add_argument("--baseline", type=Path, help="compare against this previously recorded report")
    parser.add_argument("--mode", choices=("sprite", "static", "all"), default="all")
    parser.add_argument("--list-degradations", action="store_true")
    args = parser.parse_args(argv)

    if args.list_degradations:
        for item in catalogue():
            print(f"{item['name']:24s} {item['description']}")
        return 0

    cases = [case for case in default_cases() if args.mode in ("all", case.mode)]
    report = run_benchmark(cases)
    payload = report.to_dict()

    for result in report.results:
        metrics = result.metrics
        if result.mode == "sprite":
            detail = (
                f"iou={metrics['silhouette']['iou']} "
                f"thin={metrics['thin_feature']['recovered']} "
                f"dE={metrics['color']['mean_delta_e']}"
            )
        else:
            detail = (
                f"dE={metrics['color']['mean_delta_e']} "
                f"palette={metrics['palette']['retained']} "
                f"texture={metrics['texture']['retention_ratio']}"
            )
        print(f"{result.name:44s} {detail}")
        for warning in result.warnings:
            print(f"{'':44s} WARNING {warning}")
    print(json.dumps(payload["summary"], indent=2))

    if args.out:
        print(f"wrote {report.write(args.out)}")

    if args.baseline:
        if not args.baseline.is_file():
            print(f"baseline not found: {args.baseline}", file=sys.stderr)
            return 2
        diff = compare_runs(json.loads(args.baseline.read_text(encoding="utf-8")), payload)
        for item in diff["improvements"]:
            print(f"IMPROVED  {item['case']}: {item.get('metric')} {item.get('before')} -> {item.get('after')}")
        for item in diff["regressions"]:
            print(f"REGRESSED {item['case']}: {item.get('metric')} {item.get('before')} -> {item.get('after')}")
        if diff["regressions"]:
            # Non-zero so this can gate a change rather than merely describe one.
            print(f"{len(diff['regressions'])} case(s) regressed against the baseline", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
