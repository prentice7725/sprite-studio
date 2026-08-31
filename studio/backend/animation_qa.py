# SPDX-License-Identifier: MIT
"""Run animation QA against refined frames and persist the report."""

from __future__ import annotations

import json
from pathlib import Path

from sprite_studio.spec.layout import frames_dir_rel, row_frame_rel

from studio.core.animation import AnimationQaResult, analyze_animation

from .spritegen_bridge import request_for


def _source_files(run_dir: Path, request: dict, state: str) -> list[Path]:
    manifest = json.loads((run_dir / "frames" / "frames-manifest.json").read_text(encoding="utf-8"))
    row = next((item for item in manifest.get("rows", []) if item.get("state") == state), None)
    if not row:
        raise ValueError(f"no extracted row for {state}")
    from .repair_service import repaired_files
    repaired = repaired_files(run_dir, state)
    if repaired:
        return repaired
    refined_dir = run_dir / frames_dir_rel(request, state) / "refined"
    refined = sorted(refined_dir.glob("frame-*.png")) if refined_dir.is_dir() else []
    return refined or [run_dir / row_frame_rel(row, index) for index in range(len(row.get("files", [])))]


def run_animation_qa(run_dir: Path, state: str) -> AnimationQaResult:
    request = request_for(run_dir)
    source_files = _source_files(run_dir, request, state)
    from PIL import Image
    frames = []
    for path in source_files:
        with Image.open(path) as opened:
            frames.append(opened.convert("RGBA"))
    result = analyze_animation(frames, state)
    qa_dir = run_dir / "studio" / "qa"
    qa_dir.mkdir(parents=True, exist_ok=True)
    if source_files and "repaired" in source_files[0].parts:
        source = "repaired"
    elif source_files and "refined" in source_files[0].parts:
        source = "refined"
    else:
        source = "extracted"
    payload = result.to_dict() | {"source": source, "files": [str(path) for path in source_files]}
    (qa_dir / f"{state}.animation.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result
