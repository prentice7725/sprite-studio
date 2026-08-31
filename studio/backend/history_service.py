# SPDX-License-Identifier: MIT
"""Read-only generation and take history for the Studio review surface."""

from __future__ import annotations

import json
from pathlib import Path

from sprite_studio.spec.layout import take_raw_rel

from .spritegen_bridge import request_for


def generation_history(run_dir: Path, state: str) -> list[dict]:
    history_dir = run_dir / "studio" / "history" / state
    records: list[dict] = []
    if not history_dir.is_dir():
        return records
    for path in sorted(history_dir.glob("attempt-*.json")):
        try:
            records.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return records


def take_history(run_dir: Path, state: str) -> list[dict]:
    request = request_for(run_dir)
    spec = request.get("states", {}).get(state) or {}
    result: list[dict] = []
    for take in spec.get("takes") or []:
        label = str(take.get("label") or "")
        path = run_dir / take_raw_rel(request, state, label) if label else None
        result.append({**take, "label": label, "raw": str(path) if path else None, "exists": bool(path and path.is_file())})
    return result


def summary(run_dir: Path, state: str) -> str:
    attempts = generation_history(run_dir, state)
    takes = take_history(run_dir, state)
    lines = [f"### History — `{state}`", f"- generation attempts: **{len(attempts)}**", f"- candidate takes: **{len(takes)}**"]
    if takes:
        lines.append("")
        lines.append("| Take | Frames | Raw |")
        lines.append("|---|---:|---|")
        for take in takes:
            marker = "✓" if take["exists"] else "✕"
            lines.append(f"| `{take['label']}` | {take.get('frames', '?')} | {marker} |")
    if attempts:
        latest = attempts[-1]
        lines.append("")
        lines.append(f"Latest attempt: `{latest.get('timestamp', 'unknown')}` via `{latest.get('provider', 'unknown')}`")
    return "\n".join(lines)
