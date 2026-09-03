# SPDX-License-Identifier: Apache-2.0
"""Phase 5 FastAPI adapters — review/repair, animation QA, and export."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
from PIL import Image

from studio.api.main import app
from studio.backend import anchor_service, export_service, history_service, qa_service, repair_service, spritegen_bridge
from studio.backend.run_manager import RUNS_ROOT_ENV
from studio.backend import run_manager
from studio.backend.schemas import StudioRunConfig

client = TestClient(app)


def _seed_run(tmp_path: Path, monkeypatch) -> tuple[str, Path]:
    root = tmp_path / "runs"
    monkeypatch.setenv(RUNS_ROOT_ENV, str(root))
    base = tmp_path / "base.png"
    Image.new("RGBA", (16, 16), (20, 40, 80, 255)).save(base)
    config = StudioRunConfig(
        run_id="api_phase5_test",
        character_id="hero",
        provider="grok",
        base_image=base,
        directions=("side",),
        mirrors={},
        states={"idle": {"frames": 2, "fps": 4, "loop": True, "action": "idle"}},
        preset="sword",
    )
    info = run_manager.create_run(config, root=root)
    return info.run_id, info.path


def test_review_route_maps_local_files_to_asset_urls(tmp_path: Path, monkeypatch) -> None:
    run_id, run_dir = _seed_run(tmp_path, monkeypatch)
    state = "side_idle"
    extracted = run_dir / "frames" / "side_idle" / "frame-0.png"
    extracted.parent.mkdir(parents=True)
    extracted.write_bytes(b"png-placeholder")
    manifest = run_dir / "frames" / "frames-manifest.json"
    manifest.write_text(json.dumps({"rows": [{"state": state, "files": ["frames/side_idle/frame-0.png"]}]}), encoding="utf-8")
    proposal = run_dir / "frames" / "side_idle" / "repair" / "proposals" / "frame-0.png"
    proposal.parent.mkdir(parents=True)
    proposal.write_bytes(b"proposal")

    monkeypatch.setattr(repair_service, "review_data", lambda *_args: {
        "candidates": [{"id": "candidate-1"}],
        "proposal_files": [str(proposal)],
        "repaired_files": [],
        "diff_files": [],
    })
    monkeypatch.setattr(repair_service, "summary", lambda *_args: "repair summary")
    monkeypatch.setattr(qa_service, "summary", lambda *_args: "qa summary")
    monkeypatch.setattr(history_service, "summary", lambda *_args: "history summary")

    response = client.get(f"/api/runs/{run_id}/states/{state}/review")

    assert response.status_code == 200
    body = response.json()
    assert body["frames"] == [f"/api/runs/{run_id}/assets/frames/side_idle/frame-0.png"]
    assert body["repair_proposals"] == [f"/api/runs/{run_id}/assets/frames/side_idle/repair/proposals/frame-0.png"]
    assert body["repair_candidates"] == ["candidate-1"]


def test_animation_qa_and_runtime_export_routes_use_service_results(tmp_path: Path, monkeypatch) -> None:
    run_id, run_dir = _seed_run(tmp_path, monkeypatch)
    state = "side_idle"
    qa_result = SimpleNamespace(ok=True, warnings=())
    monkeypatch.setattr(spritegen_bridge, "animation_qa", lambda *_args: qa_result)

    qa_response = client.post(f"/api/runs/{run_id}/states/{state}/animation-qa")
    assert qa_response.status_code == 200
    assert qa_response.json() == {"ok": True, "warnings": [], "summary": "Animation QA PASS — no continuity warnings."}

    atlas = run_dir / "runtime-atlas.png"
    manifest = run_dir / "runtime-manifest.json"
    atlas.write_bytes(b"atlas")
    manifest.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(export_service, "build_runtime", lambda *_args, **_kwargs: {"atlas": atlas, "manifest": manifest, "size": (48, 48)})

    export_response = client.post(f"/api/runs/{run_id}/export/runtime")
    assert export_response.status_code == 200
    body = export_response.json()
    assert body["atlas_asset"] == f"/api/runs/{run_id}/assets/runtime-atlas.png"
    assert body["manifest_asset"] == f"/api/runs/{run_id}/assets/runtime-manifest.json"
    assert body["size"] == [48, 48]


def test_repair_safe_route_runs_analysis_then_repair(tmp_path: Path, monkeypatch) -> None:
    run_id, _run_dir = _seed_run(tmp_path, monkeypatch)
    state = "side_idle"
    calls: list[str] = []
    monkeypatch.setattr(repair_service, "analyze_state", lambda *_args: calls.append("analyze"))
    monkeypatch.setattr(repair_service, "repair_state", lambda *_args: calls.append("repair"))
    monkeypatch.setattr(repair_service, "review_data", lambda *_args: {"candidates": [], "proposal_files": [], "repaired_files": [], "diff_files": []})
    monkeypatch.setattr(repair_service, "summary", lambda *_args: "repair summary")
    monkeypatch.setattr(qa_service, "summary", lambda *_args: "qa summary")
    monkeypatch.setattr(history_service, "summary", lambda *_args: "history summary")

    response = client.post(f"/api/runs/{run_id}/states/{state}/repair/safe")

    assert response.status_code == 200
    assert calls == ["analyze", "repair"]
