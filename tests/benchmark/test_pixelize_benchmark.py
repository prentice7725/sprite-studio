# SPDX-License-Identifier: Apache-2.0
from pathlib import Path

from PIL import Image

from tools.pixelize_benchmark import (
    DEFAULT_CONFIG,
    _load_config,
    _options,
    _run_method,
    _source_image,
)


def test_phase1_config_has_required_matrix():
    config = _load_config(DEFAULT_CONFIG)
    assert len(config["dataset"]["sources"]) >= 10
    assert {item["id"] for item in config["methods"]} == {"A1_current_m1_1", "A2_box", "A3_lanczos"}
    assert config["matrix"]["sizes"] == [96, 128, 192]
    assert config["matrix"]["palette_sizes"] == ["auto", 32, 48]


def test_geometry_first_candidates_are_distinct_and_deterministic():
    config = _load_config(DEFAULT_CONFIG)
    options = _options(config["matrix"], 96, "auto", "balanced")
    source = _source_image("D01")
    box = _run_method("A2_box", source, options)
    lanczos = _run_method("A3_lanczos", source, options)
    assert box[0].height == 96
    assert lanczos[0].height == 96
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