# SPDX-License-Identifier: Apache-2.0
import json
from pathlib import Path

from PIL import Image

from tools.pixelize_benchmark import (
    _load_config,
    _options,
    _run_method,
    _source_image,
)


def _test_config(tmp_path: Path) -> dict:
    config_path = tmp_path / "phase1-test-matrix.json"
    config_path.write_text(json.dumps({
        "version": 1,
        "phase": "phase1",
        "dataset": {
            "minimum_sources": 10,
            "sources": [{"id": f"D{index:02d}", "file": f"D{index:02d}.png"} for index in range(1, 11)],
        },
        "methods": [{"id": method} for method in ("A1_current_m1_1", "A2_box", "A3_lanczos")],
        "matrix": {
            "sizes": [128, 160, 192, 256],
            "palette_sizes": ["auto", 32, 48],
            "dither": "none",
            "background": "cleanup",
            "outline": "preserve",
            "alpha_threshold": 128,
        },
    }), encoding="utf-8")
    return _load_config(config_path)


def test_phase1_config_contract_uses_only_supported_heights(tmp_path: Path):
    config = _test_config(tmp_path)
    assert len(config["dataset"]["sources"]) >= 10
    assert {item["id"] for item in config["methods"]} == {"A1_current_m1_1", "A2_box", "A3_lanczos"}
    assert config["matrix"]["sizes"] == [128, 160, 192, 256]
    assert config["matrix"]["palette_sizes"] == ["auto", 32, 48]


def test_geometry_first_candidates_are_distinct_and_deterministic(tmp_path: Path):
    config = _test_config(tmp_path)
    options = _options(config["matrix"], 128, "auto", "balanced")
    source = _source_image("D01")
    box = _run_method("A2_box", source, options)
    lanczos = _run_method("A3_lanczos", source, options)
    assert box[0].height == 128
    assert lanczos[0].height == 128
    assert box[2]["profile"]["operation_order"].endswith("resize:BOX -> palette -> remap")
    assert lanczos[2]["profile"]["operation_order"].endswith("resize:LANCZOS -> palette -> remap")
    assert box[0].tobytes() != lanczos[0].tobytes()
    again = _run_method("A2_box", source, options)
    assert box[0].tobytes() == again[0].tobytes()


def test_synthetic_source_is_rgba_and_repeatable():
    first = _source_image("D07")
    second = _source_image("D07")
    assert first.mode == "RGBA"
    assert first.size == (512, 512)
    assert first.tobytes() == second.tobytes()
