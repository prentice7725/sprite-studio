# SPDX-License-Identifier: MIT
"""Studio adapter for the engine-owned directional anchor contract."""

from __future__ import annotations

from pathlib import Path

from sprite_studio.curate import anchor
from sprite_studio.curate.curation import load_curation

from .spritegen_bridge import request_for


def directions(run_dir: Path) -> list[str]:
    return anchor.directions(request_for(run_dir))


def status(run_dir: Path) -> list[dict]:
    request = request_for(run_dir)
    curation = load_curation(run_dir)
    return [anchor.anchor_status(run_dir, request, curation, direction) for direction in anchor.directions(request)]


def pin(run_dir: Path, state: str, index: int) -> dict:
    """Pin one already-extracted frame and materialize the derived anchor ref."""
    anchor.run(run_dir, pick=f"{state}#{int(index)}")
    return next(item for item in status(run_dir) if item["direction"] == anchor.state_direction(request_for(run_dir), state))


def clear(run_dir: Path, direction: str) -> dict:
    anchor.run(run_dir, direction=direction, clear=True)
    return next(item for item in status(run_dir) if item["direction"] == direction)


def summary(run_dir: Path) -> str:
    rows = ["### Direction Anchors", "| Direction | Selected frame | Source | Status |", "|---|---|---|---|"]
    for item in status(run_dir):
        frame = f"{item['state']}#{item['index']}" if item.get("state") else "—"
        source = item.get("source") or "—"
        state = "pending" if item.get("pending") else "error" if item.get("error") else "ready"
        rows.append(f"| `{item['direction']}` | `{frame}` | `{source}` | {state} |")
        if item.get("error") and not item.get("pending"):
            rows.append(f"|  |  |  | ⚠ {item['error']} |")
    return "\n".join(rows)
