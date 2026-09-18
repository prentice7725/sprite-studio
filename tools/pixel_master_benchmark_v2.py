#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Prepare a Pixel Master V2 run with an immutable Tier B input boundary.

This entry point intentionally establishes the run context before method
execution is delegated to the individual A1/A2/B1/C1/C2 adapters. Its first
stateful operation is Tier B fixture verification; output directories and run
artifacts are created only after that verification succeeds.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.tier_b_fixture_guard import (  # noqa: E402
    DEFAULT_MANIFEST,
    DEFAULT_SOURCE_ROOT,
    TierBFixtureError,
    TierBFixtureSet,
    ai_reference_plan,
    verify_tier_b_fixtures,
)


DEFAULT_CONFIG = ROOT / "benchmark_v2" / "configs" / "benchmark_matrix.json"
DEFAULT_OUT = ROOT / "benchmark_v2" / "runs"
METHODS = ("A1", "A2", "B1", "C1", "C2")


@dataclass(frozen=True)
class V2RunContext:
    config_path: Path
    output_root: Path
    methods: tuple[str, ...]
    tier_a_sources: tuple[str, ...]
    tier_b_sources: tuple[str, ...]
    tier_b_fixtures: TierBFixtureSet
    ai_references: dict[str, dict[str, Path]]


def _read_config(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read V2 benchmark config {path}: {exc}") from exc
    if payload.get("version") != 2 or payload.get("phase") != "phase2A":
        raise ValueError(f"unsupported V2 benchmark config: {path}")
    return payload


def _select(values: Iterable[str] | None, available: Iterable[str], label: str) -> tuple[str, ...]:
    allowed = tuple(available)
    selected = tuple(values) if values is not None else allowed
    unknown = sorted(set(selected) - set(allowed))
    if unknown:
        raise ValueError(f"unknown {label}: {', '.join(unknown)}")
    if len(set(selected)) != len(selected):
        raise ValueError(f"duplicate {label}: {', '.join(selected)}")
    return selected


def prepare_run(
    *,
    config_path: Path = DEFAULT_CONFIG,
    output_root: Path = DEFAULT_OUT,
    methods: Iterable[str] | None = None,
    tier_a_sources: Iterable[str] | None = None,
    tier_b_sources: Iterable[str] | None = None,
    manifest_path: Path = DEFAULT_MANIFEST,
    tier_b_root: Path = DEFAULT_SOURCE_ROOT,
) -> V2RunContext:
    """Build a verified run context without creating outputs.

    The Tier B verification is deliberately before output-root creation and
    before any adapter can receive a source path. A missing or changed Rxx
    fixture therefore aborts the run without a synthetic substitute.
    """

    config_path = config_path.resolve()
    config = _read_config(config_path)
    configured_methods = tuple(config["methods"])
    selected_methods = _select(methods, configured_methods, "methods")
    dataset = config["dataset"]
    selected_tier_a = _select(tier_a_sources, dataset["tier_a_sources"], "Tier A sources")
    selected_tier_b = _select(tier_b_sources, dataset["tier_b_sources"], "Tier B sources")

    # This is the immutable input boundary. Do not move this below any write.
    fixtures = verify_tier_b_fixtures(
        source_root=tier_b_root,
        manifest_path=manifest_path,
        required_ids=selected_tier_b,
    )
    references = ai_reference_plan(fixtures, selected_tier_b)

    return V2RunContext(
        config_path=config_path,
        output_root=output_root.resolve(),
        methods=selected_methods,
        tier_a_sources=selected_tier_a,
        tier_b_sources=selected_tier_b,
        tier_b_fixtures=fixtures,
        ai_references=references,
    )


def _write_run_manifest(context: V2RunContext) -> Path:
    """Write only the verified input manifest for this orchestration step."""

    context.output_root.mkdir(parents=True, exist_ok=True)
    manifest_path = context.output_root / "run_manifest.json"
    payload = {
        "kind": "pixel-master-benchmark-v2-run",
        "version": 1,
        "config": str(context.config_path),
        "methods": list(context.methods),
        "tier_a_sources": list(context.tier_a_sources),
        "tier_b_sources": [
            {
                "id": fixture.source_id,
                "path": str(fixture.path),
                "sha256": fixture.actual_sha256,
                "c1_reference": str(context.ai_references[fixture.source_id]["C1"]),
                "c2_reference": str(context.ai_references[fixture.source_id]["C2"]),
            }
            for fixture in context.tier_b_fixtures.fixtures
        ],
        "fixture_policy": "immutable-existing-files-only",
    }
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--methods", nargs="+", choices=METHODS, default=None)
    parser.add_argument("--tier-a-sources", nargs="+", default=None)
    parser.add_argument("--tier-b-sources", nargs="+", default=None)
    parser.add_argument("--verify-only", action="store_true", help="verify Tier B and do not write a run manifest")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        context = prepare_run(
            config_path=args.config if args.config.is_absolute() else ROOT / args.config,
            output_root=args.out if args.out.is_absolute() else ROOT / args.out,
            methods=args.methods,
            tier_a_sources=args.tier_a_sources,
            tier_b_sources=args.tier_b_sources,
        )
    except (TierBFixtureError, ValueError) as exc:
        print(f"pixel-master-benchmark-v2: stopped: {exc}", file=sys.stderr)
        return 2

    print(f"verified Tier B fixtures: {', '.join(context.tier_b_sources)}")
    if args.verify_only:
        return 0
    print(f"run manifest: {_write_run_manifest(context)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
