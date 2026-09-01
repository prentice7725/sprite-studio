# SPDX-License-Identifier: Apache-2.0
"""Test refine residual handoff to repair pipeline."""

from __future__ import annotations

from PIL import Image

from studio.core.repair.repair_pipeline import RepairPipeline


def test_residual_handoff_creates_repair_candidate():
    # 8x8 frame with transparent background and a single colored pixel at (3, 3)
    frame = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
    frame.putpixel((3, 3), (255, 0, 0, 255))
    
    # Residual specifies a lost thin feature at (3, 4) next to (3, 3)
    residuals = [
        {
            "frame": 0,
            "type": "thin_feature_at_risk",
            "logical_region": {"x": 3, "y": 4, "w": 1, "h": 1},
            "pixels": [[3, 4]],
            "evidence": {"protected_pixels": 1, "rescued_cells": 0},
            "hint": "repair layer should verify thin-feature continuity",
        }
    ]
    
    pipeline = RepairPipeline()
    candidates = pipeline.analyze([frame], state="test_state", residuals=residuals)
    
    # Find candidate created from residual
    residual_cands = [c for c in candidates if c.details.get("source") == "refine_residual"]
    assert len(residual_cands) >= 1
    cand = residual_cands[0]
    assert cand.frame == 0
    assert cand.type == "thin_feature_at_risk"
    assert cand.pixels == ((3, 4),)
    assert cand.action == "add"
    assert cand.color == (255, 0, 0, 255)  # Inherits neighbor color
    
    # Test repair execution with this candidate
    result = pipeline.repair([frame], state="test_state", residuals=residuals)
    repaired_frame = result.frames[0]
    # Verify the pixel was added
    assert repaired_frame.getpixel((3, 4))[3] == 255
