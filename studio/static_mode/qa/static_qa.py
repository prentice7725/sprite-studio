# SPDX-License-Identifier: Apache-2.0
"""Static QA (spec §14.2).

Sprite QA asks whether a row holds together over time. Static QA asks whether
one image holds together in space, so the checks are entirely different:

* **edge cleanliness** — leftover semi-transparent fringe that will halo.
* **scene readability** — enough tonal structure to read at target size, and
  not so much noise that the palette is meaningless.
* **palette consistency** — entries that carry no area, or sit so close
  together they are one entry wearing two hats.
* **seam integrity** — only when the project declares itself tileable.
* **layer separation** — whether a split actually separated anything.

Diagnostic, never corrective: a warning here is evidence for an operator, not a
trigger for an automatic edit.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from PIL import Image

from studio.shared.config import RefineSettings, StaticQaSettings, load_qa_settings
from studio.static_mode.refine.palette import palette_usage, tone_consistency
from studio.static_mode.tile.seam import check_seams


@dataclass(frozen=True)
class StaticQaResult:
    asset_type: str
    ok: bool
    metrics: dict[str, Any]
    warnings: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "asset-studio-static-qa",
            "asset_type": self.asset_type,
            "ok": self.ok,
            "metrics": self.metrics,
            "warnings": [dict(warning) for warning in self.warnings],
        }


def _edge_cleanliness(image: Image.Image) -> dict[str, Any]:
    alpha = np.asarray(image.convert("RGBA"), dtype=np.uint8)[:, :, 3]
    soft = int(np.count_nonzero((alpha > 0) & (alpha < 255)))
    opaque = int(np.count_nonzero(alpha >= 128))
    return {
        "soft_alpha_pixels": soft,
        "opaque_pixels": opaque,
        "soft_ratio": round(soft / max(1, soft + opaque), 6),
    }


def run_static_qa(
    image: Image.Image,
    settings: RefineSettings,
    *,
    qa_settings: StaticQaSettings | None = None,
    asset_type: str = "PIXEL_SCENE",
    palette: tuple[tuple[int, int, int, int], ...] = (),
    tileable: bool = False,
    layers: int | None = None,
) -> StaticQaResult:
    qa_config = qa_settings or load_qa_settings("static")
    warnings: list[dict[str, Any]] = []
    edges = _edge_cleanliness(image)
    if edges["soft_ratio"] > qa_config.soft_ratio_threshold:
        warnings.append(
            {
                "severity": "warning",
                "code": "soft-edges",
                "message": f"{edges['soft_alpha_pixels']} semi-transparent pixels remain; they will halo when composited",
            }
        )

    tone = tone_consistency(image)
    metrics: dict[str, Any] = {"edges": edges, "tone": tone}

    if palette:
        usage = palette_usage(image, palette)
        metrics["palette"] = usage
        if usage["unused"]:
            warnings.append(
                {
                    "severity": "info",
                    "code": "palette-unused",
                    "indices": usage["unused"],
                    "message": "palette entries carry no area; the palette is larger than the image needs",
                }
            )
        separation = usage.get("separation") or {}
        if separation.get("min_delta_e") is not None and separation["min_delta_e"] < qa_config.min_delta_e_threshold:
            warnings.append(
                {
                    "severity": "warning",
                    "code": "palette-collapsed",
                    "message": f"two palette entries are {separation['min_delta_e']:.4f} apart in Oklab and will read as one colour",
                }
            )

    if tileable:
        seam = check_seams(image, settings.seam)
        metrics["seam"] = seam.to_dict()
        if not seam.ok:
            warnings.append(
                {
                    "severity": "error",
                    "code": "seam-open",
                    "message": f"tile seams exceed threshold (h={seam.horizontal:.4f}, v={seam.vertical:.4f}, limit={seam.threshold})",
                }
            )

    if layers is not None:
        metrics["layers"] = layers
        if layers < qa_config.min_layers:
            warnings.append(
                {
                    "severity": "info",
                    "code": "layer-split-flat",
                    "message": "the layer split produced a single layer; this scene has no separable background",
                }
            )

    ok = not any(warning["severity"] == "error" for warning in warnings)
    return StaticQaResult(asset_type=asset_type, ok=ok, metrics=metrics, warnings=tuple(warnings))
