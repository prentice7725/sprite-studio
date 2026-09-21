# SPDX-License-Identifier: Apache-2.0

from pathlib import Path

from tools import pixel_master_benchmark_v2 as preparation
from tools import pixel_master_benchmark_v2_execute as executor


ROOT = Path(__file__).resolve().parents[2]


def _smoke_context(output_root: Path):
    return preparation.prepare_run(
        config_path=ROOT / "benchmark_v2" / "configs" / "benchmark_matrix_r00_r08.json",
        output_root=output_root,
        methods=("A1", "A2", "B1", "C1", "C2"),
        tier_a_sources=(),
        tier_b_sources=("R00", "R03", "R06"),
        manifest_path=ROOT / "benchmark_v2" / "configs" / "tier_b_fixtures_r00_r08.json",
        tier_b_root=ROOT / "benchmark_v2" / "sources" / "tier_b",
    )


def test_rebench_runner_records_missing_ai_sidecars_without_resizing_transport(tmp_path: Path) -> None:
    output_root = tmp_path / "smoke"
    context = _smoke_context(output_root)

    rows = executor.run_phase_2a(
        context,
        output_root=output_root,
        ai_input_root=ROOT / "benchmark_v2" / "ai_inputs",
        force=True,
    )

    ai_rows = [row for row in rows if row["method_id"] in {"C1", "C2"}]
    assert len(ai_rows) == 6
    assert {row["status"] for row in ai_rows} == {"FAIL_PROVENANCE"}
    assert all(not row["logical_path"] for row in ai_rows)
    assert all(row["transport_path"] for row in ai_rows)
    summary = (output_root / "reports" / "smoke_summary.md").read_text(encoding="utf-8")
    assert "3 sources × 5 methods = 15 method results" in summary
    assert "winner:" not in summary.lower()


def test_rebench_contact_sheet_uses_logical_tiles_only(tmp_path: Path) -> None:
    output_root = tmp_path / "smoke"
    context = _smoke_context(output_root)

    executor.run_phase_2a(
        context,
        output_root=output_root,
        ai_input_root=ROOT / "benchmark_v2" / "ai_inputs",
        force=True,
    )

    assert (output_root / "sheets" / "by_source" / "R00.png").is_file()
    assert (output_root / "sheets" / "ai_audit" / "C1.png").is_file()
    assert not (output_root / "sheets" / "by_source" / "raw").exists()
