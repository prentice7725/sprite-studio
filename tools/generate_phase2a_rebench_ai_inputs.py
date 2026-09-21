#!/usr/bin/env python3
"""Generate auditable C1/C2 transport inputs for the Phase 2A smoke set."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from studio.static_mode.pixelize.c1 import C1Options, c1_pixel_master_file  # noqa: E402
from studio.static_mode.pixelize.c2 import C2Options, c2_pixel_master_file  # noqa: E402


DEFAULT_SOURCE_ROOT = ROOT / "benchmark_v2" / "sources" / "tier_b"
DEFAULT_OUTPUT_ROOT = ROOT / "benchmark_v2" / "phase2A_rebench_128logical" / "generated_ai"
DEFAULT_INPUT_ROOT = DEFAULT_OUTPUT_ROOT / "inputs"
SOURCES = ("R00", "R03", "R06")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _prompt_sha256(report: dict[str, Any]) -> str:
    provider = report["transport"]["provider"]
    prompt = str(provider["prompt"])
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def _provider_fields(report: dict[str, Any]) -> tuple[str, str, str]:
    provider = report["transport"]["provider"]
    name = str(provider["provider"])
    model = str(provider.get("model") or "grok-build")
    return name, model, _prompt_sha256(report)


def _write_sidecar(
    *,
    sidecar_path: Path,
    source_id: str,
    method: str,
    source_path: Path,
    transport_path: Path,
    report: dict[str, Any],
    intermediate_path: Path | None = None,
) -> None:
    provider, model, prompt_sha256 = _provider_fields(report)
    payload: dict[str, Any] = {
        "source_id": source_id,
        "method": method,
        "stage": "final-128-logical-transport",
        "provider": provider,
        "model": model,
        "prompt_sha256": prompt_sha256,
        "source_sha256": _sha256(source_path),
        "transport_sha256": _sha256(transport_path),
    }
    if intermediate_path is not None:
        payload["intermediate_sha256"] = _sha256(intermediate_path)
        payload["intermediate_path"] = os.path.relpath(intermediate_path, sidecar_path.parent)
    sidecar_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _copy_transport(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)


def generate(*, provider: str, source_root: Path, output_root: Path, input_root: Path) -> dict[str, Any]:
    output_root.mkdir(parents=True, exist_ok=True)
    input_root.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []

    for source_id in SOURCES:
        source_path = (source_root / f"{source_id}.png").resolve()
        if not source_path.is_file():
            raise FileNotFoundError(f"Tier B source not found: {source_path}")

        c1_dir = output_root / "production" / "C1" / source_id
        print(f"[C1 {source_id}] generating transport with {provider}", flush=True)
        c1 = c1_pixel_master_file(
            source_path,
            c1_dir,
            provider=provider,
            options=C1Options(target_size=128),
            stem=source_id,
            workdir=output_root / "work" / "C1" / source_id,
        )
        c1_input = input_root / "C1" / f"{source_id}.png"
        _copy_transport(c1.transport_path, c1_input)
        c1_sidecar = c1_input.with_suffix(".json")
        _write_sidecar(
            sidecar_path=c1_sidecar,
            source_id=source_id,
            method="C1",
            source_path=source_path,
            transport_path=c1_input,
            report=c1.report,
        )
        records.append({
            "source_id": source_id,
            "method": "C1",
            "transport": str(c1_input),
            "sidecar": str(c1_sidecar),
            "production_report": str(c1.report_path),
            "logical_gate_status": c1.report["status"],
        })

        c2_dir = output_root / "production" / "C2" / source_id
        print(f"[C2 {source_id}] generating stage1 + stage2 transport with {provider}", flush=True)
        c2 = c2_pixel_master_file(
            source_path,
            c2_dir,
            provider=provider,
            options=C2Options(target_size=128),
            stem=source_id,
            workdir=output_root / "work" / "C2" / source_id,
        )
        c2_input = input_root / "C2" / f"{source_id}.png"
        _copy_transport(c2.transport_path, c2_input)
        c2_intermediate = input_root / "intermediate" / "C2" / f"{source_id}.png"
        _copy_transport(c2.intermediate_path, c2_intermediate)
        c2_sidecar = c2_input.with_suffix(".json")
        _write_sidecar(
            sidecar_path=c2_sidecar,
            source_id=source_id,
            method="C2",
            source_path=source_path,
            transport_path=c2_input,
            report=c2.report,
            intermediate_path=c2_intermediate,
        )
        records.append({
            "source_id": source_id,
            "method": "C2",
            "transport": str(c2_input),
            "intermediate": str(c2_intermediate),
            "sidecar": str(c2_sidecar),
            "production_report": str(c2.report_path),
            "logical_gate_status": c2.report["status"],
        })

    manifest = {
        "kind": "phase2a-rebench-generated-ai-inputs",
        "version": 1,
        "provider": provider,
        "sources": list(SOURCES),
        "methods": ["C1", "C2"],
        "input_root": str(input_root.resolve()),
        "records": records,
    }
    manifest_path = output_root / "generation_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=("grok", "codex"), default="grok")
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--input-root", type=Path, default=DEFAULT_INPUT_ROOT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest = generate(
        provider=args.provider,
        source_root=(args.source_root if args.source_root.is_absolute() else ROOT / args.source_root).resolve(),
        output_root=(args.output_root if args.output_root.is_absolute() else ROOT / args.output_root).resolve(),
        input_root=(args.input_root if args.input_root.is_absolute() else ROOT / args.input_root).resolve(),
    )
    print(f"generated {len(manifest['records'])} AI transport records")
    print(f"manifest: {manifest['input_root']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
