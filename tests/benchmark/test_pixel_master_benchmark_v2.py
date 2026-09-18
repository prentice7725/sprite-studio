# SPDX-License-Identifier: Apache-2.0
from pathlib import Path

from tools.pixel_master_benchmark_v2 import DEFAULT_CONFIG, prepare_run


def test_v2_prepare_run_verifies_tier_b_before_context_is_returned():
    context = prepare_run(
        config_path=DEFAULT_CONFIG,
        methods=["C1", "C2"],
        tier_a_sources=["D01"],
        tier_b_sources=["R01", "R03"],
    )

    assert context.tier_b_sources == ("R01", "R03")
    assert context.ai_references["R01"]["C1"] is context.ai_references["R01"]["C2"]
    assert context.ai_references["R03"]["C1"] is context.ai_references["R03"]["C2"]
    assert all(path.parent == Path(context.tier_b_fixtures.source_root) for path in context.ai_references["R01"].values())
