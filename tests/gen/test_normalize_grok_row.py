from __future__ import annotations

import json
import shutil
from pathlib import Path

from PIL import Image, ImageDraw

from sprite_studio.frames.extract import extract_component_images, remove_chroma_background
from sprite_studio.gen.normalize_grok_row import normalize_image, run
from conftest import run_script


def _four_subjects() -> Image.Image:
    image = Image.new("RGB", (640, 180), (0, 255, 0))
    draw = ImageDraw.Draw(image)
    for index, color in enumerate(((220, 40, 40), (40, 80, 220), (220, 180, 30), (150, 50, 190))):
        left = 35 + index * 150
        draw.rectangle((left, 28, left + 82, 155), fill=color)
        draw.rectangle((left + 24, 10, left + 58, 45), fill=color)
    return image


def test_normalize_image_produces_one_cell_per_subject() -> None:
    output, report = normalize_image(
        _four_subjects(),
        (0, 255, 0),
        count=4,
        cell_width=64,
        cell_height=64,
        safe_margin_x=4,
        safe_margin_y=4,
    )

    assert output.mode == "RGBA"
    assert output.size == (256, 64)
    assert report["segmentation"]["natural_count"] == 4
    assert len(report["subjects"]) == 4
    for index in range(4):
        cell = output.crop((index * 64, 0, (index + 1) * 64, 64))
        assert cell.getbbox() is not None
        assert sum(cell.getchannel("A").histogram()[1:]) > 100

    downstream = extract_component_images(
        remove_chroma_background(output, (0, 255, 0), 96.0, 180.0, 18.0),
        4,
    )
    assert downstream is not None
    assert len(downstream) == 4


def test_normalize_run_writes_report_and_chroma_background(tmp_path: Path) -> None:
    source = tmp_path / "wide.png"
    output = tmp_path / "row.png"
    report_path = tmp_path / "row.report.json"
    _four_subjects().save(source)

    assert run(
        input=source,
        out=output,
        count=4,
        cell_width=64,
        cell_height=64,
        safe_margin=4,
        background="chroma",
        report=report_path,
    ) == 0

    assert Image.open(output).mode == "RGB"
    assert Image.open(output).size == (256, 64)
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["kind"] == "sprite-studio-grok-row-normalization"
    assert payload["background"] == "chroma"
    assert payload["output"] == str(output.resolve())


def test_extract_can_normalize_selected_wide_raw_in_place(tmp_path: Path) -> None:
    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "run"
    run_dir = tmp_path / "run"
    shutil.copytree(fixture, run_dir)
    request_path = run_dir / "sprite-request.json"
    request = json.loads(request_path.read_text(encoding="utf-8"))
    request["chroma_key"] = {
        "name": "green",
        "hex": "#00FF00",
        "rgb": [0, 255, 0],
        "selection": "test",
    }
    request_path.write_text(json.dumps(request), encoding="utf-8")
    _four_subjects().save(run_dir / "raw" / "idle.png")

    result = run_script(
        "extract_sprite_row_frames.py",
        "--run-dir",
        str(run_dir),
        "--states",
        "idle",
        "--normalize-grok-row",
    )

    assert result.returncode == 0, result.stdout + result.stderr
    with Image.open(run_dir / "raw" / "idle.png") as normalized:
        assert normalized.size == (384, 96)
        assert normalized.mode == "RGBA"
    assert (run_dir / "raw" / "idle.normalize.report.json").is_file()
    manifest = json.loads((run_dir / "frames" / "frames-manifest.json").read_text(encoding="utf-8"))
    assert manifest["ok"] is True
