# SPDX-License-Identifier: Apache-2.0
"""Quick Generate adapter for identity-preserving Auto Resolution."""

from __future__ import annotations

from typing import Any

from PIL import Image

from studio.backend import quick_service
from studio.static_mode.pixelize import IdentityFeatureManifest, SemanticPseOptions, d2_semantic_auto_file


def pixelize_auto_session(session_id: str, body: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    payload = quick_service.load_session(session_id)
    root = quick_service._session_dir(session_id)
    source = root / "source" / "original.png"
    if not source.is_file():
        raise FileNotFoundError("quick source image is missing")
    if not body.identity_manifest:
        raise ValueError("identity_preserving_auto requires an Identity Feature Manifest")
    manifest = IdentityFeatureManifest.from_dict(body.identity_manifest)
    result = d2_semantic_auto_file(
        source,
        root / "pixelized",
        # Identity masters use GPT Image semantic redraw regardless of the
        # provider that created the original Quick source.
        provider="codex",
        manifest=manifest,
        options=SemanticPseOptions(
            palette_size=None if body.palette == "auto" else int(body.palette),
            alpha_threshold=int(body.alpha_threshold),
        ),
        stem="source",
        workdir=root / "work" / "identity-auto",
        audit=str(getattr(body, "resolution_mode", "AUTO")) == "AUDIT",
        override_height=getattr(body, "resolution_override", None),
    )
    if result.accepted_path is None or result.preview_path is None:
        raise ValueError(str(result.report.get("status") or "NO_VALID_RESOLUTION"))
    with Image.open(result.accepted_path) as opened:
        logical = opened.convert("RGBA")
    alpha = logical.getchannel("A")
    bbox = alpha.getbbox()
    if bbox is None:
        raise ValueError("accepted auto-resolution master has no subject")
    relative = {
        "semantic": "pixelized/semantic/source.png",
        "intermediate": "pixelized/intermediate/source.png",
        "logical": "pixelized/logical/source.png",
        "preview": "pixelized/logical/source.preview-4x.png",
        "report": "pixelized/report.json",
    }
    payload.update({
        "pixelize_strategy": "identity_preserving_auto",
        "pixelize_accepted": "logical_master",
        "pixelized_source": relative["logical"],
        "pixelized_preview": relative["preview"],
        "subject_source": relative["logical"],
        "pixelized_semantic_source": relative["semantic"],
        "pixelized_intermediate_source": relative["intermediate"],
        "pixelized_report": relative["report"],
        "pixelize_options": body.model_dump(),
        "identity_manifest": manifest.to_dict(),
        "pixelize_semantic_provider": "codex",
        "pixelize_semantic_provider_role": "GPT Image semantic redraw via Codex image_gen",
    })
    quick_service._write(session_id, payload)
    base_url = f"/api/quick/sessions/{session_id}/assets/"
    return payload, {
        "session_id": session_id,
        "strategy": "identity_preserving_auto",
        "accepted": "logical_master",
        "output_source": base_url + relative["logical"],
        "preview_source": base_url + relative["preview"],
        "subject_source": base_url + relative["logical"],
        "raw_source": base_url + relative["semantic"],
        "intermediate_source": base_url + relative["intermediate"],
        "post_source": base_url + relative["logical"],
        "subject_bbox": list(bbox),
        "subject_candidates": [],
        "logical_size": list(logical.size),
        "palette_size": int(result.report.get("resolution", {}).get("candidate_details", {}).get(str(result.selected_height), {}).get("logical_validation", {}).get("metrics", {}).get("palette_size", 0)),
        "palette": [],
        "warnings": [
            *result.report.get("semantic_quality", {}).get("warnings", []),
            *result.report.get("warnings", []),
        ],
        "report": result.report,
        "resolution": result.report.get("resolution"),
    }


__all__ = ["pixelize_auto_session"]
