from __future__ import annotations

from pathlib import Path

from tools import pixel_master_benchmark_phase2b_execute as executor
from tools import pixel_master_benchmark_v2 as preparation


ROOT = Path(__file__).resolve().parents[2]


def test_phase2b_contract_keeps_only_logical_outputs_in_ranking(tmp_path: Path, monkeypatch) -> None:
    output_root = tmp_path / "phase2b"
    context = preparation.prepare_run(
        config_path=ROOT / "benchmark_v2" / "configs" / "benchmark_matrix_r00_r08.json",
        output_root=output_root,
        methods=("A1", "A2", "B1"),
        tier_a_sources=(),
        tier_b_sources=("R00",),
        manifest_path=ROOT / "benchmark_v2" / "configs" / "tier_b_fixtures_r00_r08.json",
        tier_b_root=ROOT / "benchmark_v2" / "sources" / "tier_b",
    )

    def fake_d1(source_path, production_dir, **kwargs):
        production_dir.mkdir(parents=True, exist_ok=True)
        semantic = production_dir / "semantic" / "R00.png"
        semantic.parent.mkdir(parents=True, exist_ok=True)
        semantic.write_bytes((ROOT / "benchmark_v2" / "sources" / "tier_b" / "R00.png").read_bytes())
        return type("Result", (), {"semantic_path": semantic, "accepted_path": None, "intermediate_path": None, "report": {"status": "FAIL_NOT_ABSTRACTED", "semantic": {"provider": {"provider": "fake", "model": "fake", "prompt": "fake"}}, "semantic_quality": {"status": "FAIL_NOT_ABSTRACTED", "warnings": []}}})()

    def fake_d2(source_path, production_dir, **kwargs):
        return fake_d1(source_path, production_dir, **kwargs)

    monkeypatch.setattr(executor, "d1_semantic_pse_file", fake_d1)
    monkeypatch.setattr(executor, "d2_semantic_pse_file", fake_d2)
    rows = executor.run_phase_2b(context, output_root=output_root, provider="grok", force=True)

    assert {row["method_id"] for row in rows} == set(executor.METHODS)
    assert all(row["method_id"] in {"A1", "A2", "B1"} or not row["logical_path"] for row in rows)
    summary = (output_root / "reports" / "smoke_summary.md").read_text(encoding="utf-8")
    assert "1 sources × 5 methods = 5 method results" in summary
    assert "winner:" not in summary.lower()
