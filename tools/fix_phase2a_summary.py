#!/usr/bin/env python3
"""Correct generated Phase 2A summary cardinalities for a completed run."""

from __future__ import annotations

import csv
import re
import sys
from pathlib import Path


def main() -> int:
    report_root = Path(sys.argv[1])
    summary_path = report_root / "benchmark_summary.md"
    objective_path = report_root / "objective_scores.csv"
    rows = list(csv.DictReader(objective_path.open(encoding="utf-8", newline="")))
    source_ids = sorted({row["source_id"] for row in rows})
    methods = sorted({row["method_id"] for row in rows})
    states = sorted({row["state"] for row in rows})
    source_text = ", ".join(source_ids)
    summary = summary_path.read_text(encoding="utf-8")
    summary = re.sub(
        r"^- Sources: .*?$",
        f"- Sources: {len(source_ids)} (Tier A: none; Tier B: {source_text})",
        summary,
        flags=re.MULTILINE,
    )
    summary = re.sub(
        r"^- Completed artifacts: .*?$",
        f"- Completed artifacts: {len(rows)} ({len(source_ids)} sources × {len(methods)} methods × {len(states)} states)",
        summary,
        flags=re.MULTILINE,
    )
    summary_path.write_text(summary, encoding="utf-8")
    print(summary_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
