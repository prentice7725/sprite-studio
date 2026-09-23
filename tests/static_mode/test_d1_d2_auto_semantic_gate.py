from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from studio.static_mode.pixelize import FeatureRegion, IdentityFeature, IdentityFeatureManifest
from studio.static_mode.pixelize.d1_d2 import SemanticPseOptions
from studio.static_mode.pixelize.d1_d2_auto import _run_auto
from studio.static_mode.pixelize.resolution import AUTO_LOGICAL_HEIGHTS
from studio.static_mode.pixelize.semantic_pixel_quality import SemanticPixelQualityResult


def test_semantic_quality_failure_stops_before_identity_review_or_pse(monkeypatch) -> None:
    source_path = Path("benchmark_v2/sources/tier_b/R00.png").resolve()
    writes: list[tuple[Path, str]] = []

    monkeypatch.setattr(
        "studio.static_mode.pixelize.d1_d2_auto.evaluate_semantic_source",
        lambda image, **kwargs: SemanticPixelQualityResult(
            "FAIL_NOT_ABSTRACTED",
            {"edge_softness_ratio": 0.4, "adjacent_transition_ratio": 0.9},
            ({"code": "FAIL_NOT_ABSTRACTED"},),
        ),
    )
    monkeypatch.setattr(
        "studio.static_mode.pixelize.d1_d2_auto.project_auto_resolution",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("PSE must not run after semantic rejection")),
    )
    monkeypatch.setattr(
        "studio.static_mode.pixelize.d1_d2_auto.atomic_write_text",
        lambda path, text: writes.append((path, text)),
    )
    manifest = IdentityFeatureManifest(
        source_id="R00",
        features=(IdentityFeature(
            id="face", label="recognizable face", importance="CRITICAL", kind="FACE",
            region=FeatureRegion(0.3, 0.1, 0.4, 0.4),
        ),),
    )

    accepted, report, selected_height = _run_auto(
        source_path=source_path,
        semantic_path=source_path,
        logical_path=Path("not-written/logical/R00.png"),
        preview_path=Path("not-written/logical/R00.preview-4x.png"),
        report_path=Path("not-written/report.json"),
        semantic_provider={"provider": "gpt-image"},
        manifest=manifest,
        options=SemanticPseOptions(),
        strategy="semantic_d1_auto_resolution_test",
        audit=True,
    )

    assert accepted is None
    assert selected_height is None
    assert report["status"] == "FAIL_NOT_ABSTRACTED"
    assert report["accepted_path"] is None
    assert report["resolution"]["root_cause"] == "SEMANTIC_QUALITY_GATE"
    assert report["resolution"]["candidate_results"] == {
        str(height): "NOT_REQUIRED_SEMANTIC_QUALITY_REJECTED" for height in AUTO_LOGICAL_HEIGHTS
    }
    assert report["pse"] == "NOT_RUN_SEMANTIC_QUALITY_REJECTED"
    assert report["semantic_preservation"]["identity_review"] is None
    assert len(writes) == 1
    assert json.loads(writes[0][1])["status"] == "FAIL_NOT_ABSTRACTED"


def test_audit_candidate_directory_is_created_before_png_write(monkeypatch) -> None:
    source_path = Path("benchmark_v2/sources/tier_b/R00.png").resolve()
    made_dirs: list[Path] = []
    saved: list[Path] = []
    resolution = SimpleNamespace(
        status="NO_VALID_RESOLUTION",
        selected_height=None,
        selected_image=None,
        semantic_preservation=SimpleNamespace(to_dict=lambda: {"pass": True, "status": "PASS"}),
        candidate_results={},
        candidate_images={128: Image.new("RGBA", (64, 128), (0, 0, 0, 0))},
        decision_report={"candidate_details": {"128": {}}},
        to_dict=lambda: {"candidate_details": {"128": {}}},
    )
    monkeypatch.setattr(
        "studio.static_mode.pixelize.d1_d2_auto.evaluate_semantic_source",
        lambda image, **kwargs: SemanticPixelQualityResult("PASS_SEMANTIC_SOURCE", {}, ()),
    )
    monkeypatch.setattr(
        "studio.static_mode.pixelize.d1_d2_auto.project_auto_resolution",
        lambda *args, **kwargs: resolution,
    )
    monkeypatch.setattr(
        "studio.static_mode.pixelize.d1_d2_auto.atomic_save_image",
        lambda image, path: saved.append(Path(path)),
    )
    monkeypatch.setattr("studio.static_mode.pixelize.d1_d2_auto.atomic_write_text", lambda path, text: None)
    monkeypatch.setattr(Path, "mkdir", lambda self, *args, **kwargs: made_dirs.append(self))

    _run_auto(
        source_path=source_path,
        semantic_path=source_path,
        logical_path=Path("audit-output/logical/R00.png"),
        preview_path=Path("audit-output/logical/R00.preview-4x.png"),
        report_path=Path("audit-output/report.json"),
        semantic_provider={"provider": "gpt-image"},
        manifest=IdentityFeatureManifest(source_id="R00", features=()),
        options=SemanticPseOptions(),
        strategy="audit-test",
        audit=True,
    )

    expected_parent = Path("audit-output/logical/candidates/R00")
    assert expected_parent in made_dirs
    assert saved == [expected_parent / "H128.png", expected_parent / "H128.preview-4x.png"]
