# SPDX-License-Identifier: Apache-2.0
"""Quick Generate adapter for the first-class C2 Pixel Master strategy."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from studio.backend import quick_service
from studio.static_mode.pixelize.c2 import C2Options, c2_pixel_master_file


def pixelize_c2_session(session_id: str, body: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run reference-guided C2 without falling back to deterministic pixelize."""

    payload = quick_service.load_session(session_id)
    root = quick_service._session_dir(session_id)
    source = root / "source" / "original.png"
    if not source.is_file():
        raise FileNotFoundError("quick source image is missing")
    if int(body.size) != 128:
        raise ValueError("reference_pixel_master_128 requires size=128")

    result = c2_pixel_master_file(
        source,
        root / "pixelized",
        provider=str(payload.get("provider") or "grok"),
        options=C2Options(
            target_size=128,
            palette_size=None if body.palette == "auto" else int(body.palette),
            alpha_threshold=int(body.alpha_threshold),
            accepted=str(getattr(body, "accepted", "post")),
        ),
        stem="source",
        workdir=root / "work" / "c2",
    )
    if result.accepted_path is None or result.post_path is None:
        status = str(result.report.get("status") or "FAIL_LOGICAL_GRID")
        raise ValueError(status)
    relative = {
        "raw": "pixelized/raw/source.png",
        "intermediate": "pixelized/intermediate/source.png",
        "post": "pixelized/post/source.png",
        "preview": "pixelized/post/source.preview-4x.png",
        "report": "pixelized/report.json",
    }
    payload.update({
        "pixelize_strategy": "reference_pixel_master_128",
        "pixelize_accepted": str(getattr(body, "accepted", "post")),
        "pixelized_source": relative["post"],
        "pixelized_preview": relative["preview"],
        "subject_source": relative["post"],
        "pixelized_raw_source": relative["raw"],
        "pixelized_intermediate_source": relative["intermediate"],
        "pixelized_post_source": relative["post"],
        "pixelized_report": relative["report"],
        "pixelize_options": body.model_dump(),
    })
    quick_service._write(session_id, payload)
    base_url = f"/api/quick/sessions/{session_id}/assets/"
    accepted = str(getattr(body, "accepted", "post"))
    return payload, {
        "session_id": session_id,
        "strategy": "reference_pixel_master_128",
        "accepted": accepted,
        "output_source": base_url + relative[accepted],
        "preview_source": base_url + relative["preview"],
        "subject_source": base_url + relative["post"],
        "raw_source": base_url + relative["raw"],
        "intermediate_source": base_url + relative["intermediate"],
        "post_source": base_url + relative["post"],
        "subject_bbox": list(result.subject_bbox),
        "subject_candidates": [],
        "logical_size": list(result.logical_size),
        "palette_size": len(result.palette),
        "palette": [list(entry) for entry in result.palette[:128]],
        "warnings": list(result.warnings),
        "report": result.report,
    }


__all__ = ["pixelize_c2_session"]
