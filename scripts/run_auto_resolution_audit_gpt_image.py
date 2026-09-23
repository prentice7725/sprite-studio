from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from studio.static_mode.pixelize.d1_d2 import SemanticPseOptions, _d1_prompt, _d2_stage1_prompt, _d2_stage2_prompt
from studio.static_mode.pixelize.d1_d2_auto import _run_auto
from studio.static_mode.pixelize.identity_manifest import manifest_from_json
from studio.static_mode.pixelize.identity_review import generate_identity_manifest, review_identity_candidate_grid
from studio.static_mode.pixelize.resolution import AUTO_LOGICAL_HEIGHTS
from studio.static_mode.pixelize.semantic_pixel_quality import evaluate_semantic_source


ROOT = Path(__file__).resolve().parents[1]
RUN_ROOT = ROOT / "benchmark_v2" / "auto_resolution_audit_gpt_image_r00_r08"
SOURCE_ROOT = ROOT / "benchmark_v2" / "sources" / "tier_b"
SMOKE_ROOT = ROOT / "benchmark_v2" / "phase2B_semantic_pse" / "smoke_gpt_image"
SOURCE_IDS = tuple(f"R{i:02d}" for i in range(9))
METHODS = ("D1", "D2")
REUSED_SOURCE_IDS = ("R00", "R03", "R06")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _copy_verified(source: Path, destination: Path, expected_sha256: str | None = None) -> str:
    source = source.resolve()
    destination = destination.resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Expected image/artifact is missing: {source}")
    digest = sha256_file(source)
    if expected_sha256 and digest != expected_sha256:
        raise ValueError(f"SHA-256 mismatch for {source}: expected {expected_sha256}, got {digest}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if sha256_file(destination) != digest:
            raise FileExistsError(f"Refusing to overwrite different audit artifact: {destination}")
    else:
        shutil.copy2(source, destination)
    return digest


def _source(source_id: str) -> Path:
    path = SOURCE_ROOT / f"{source_id}.png"
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def _gpt_dir(method: str, source_id: str) -> Path:
    return RUN_ROOT / "_gpt" / method / source_id


def generate_ifms(source_ids: tuple[str, ...]) -> None:
    for source_id in source_ids:
        source = _source(source_id)
        folder = RUN_ROOT / "ifm" / source_id
        manifest_path = folder / "identity_feature_manifest.json"
        provenance_path = folder / "identity_feature_manifest_provenance.json"
        if manifest_path.is_file() and provenance_path.is_file():
            provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
            if provenance.get("source_sha256") == sha256_file(source):
                print(f"IFM {source_id}: reusing matching draft", flush=True)
                continue
        manifest, provenance = generate_identity_manifest(source, source_id, workdir=folder)
        print(
            f"IFM {source_id}: {len(manifest.features)} features; "
            f"sha256={provenance['manifest_sha256']}",
            flush=True,
        )


def record_generated_image(method: str, source_id: str, stage: str, saved_path: Path) -> Path:
    if method not in METHODS or source_id not in SOURCE_IDS:
        raise ValueError("method/source_id is outside the fixed audit matrix")
    if method == "D1" and stage != "raw":
        raise ValueError("D1 generation stage must be 'raw'")
    if method == "D2" and stage not in {"stage1", "stage2"}:
        raise ValueError("D2 generation stage must be 'stage1' or 'stage2'")
    source = _source(source_id)
    gpt_dir = _gpt_dir(method, source_id)
    destination = gpt_dir / ("raw.png" if stage == "raw" else f"{stage}.png")
    saved_path = saved_path.expanduser().resolve()
    digest = _copy_verified(saved_path, destination)
    source_refs = [source]
    if method == "D2" and stage == "stage2":
        source_refs.append(gpt_dir / "stage1.png")
        if not source_refs[-1].is_file():
            raise FileNotFoundError("D2 stage2 requires the recorded stage1 image")
    prompt = {
        ("D1", "raw"): _d1_prompt(),
        ("D2", "stage1"): _d2_stage1_prompt(),
        ("D2", "stage2"): _d2_stage2_prompt(),
    }[(method, stage)]
    generation = {
        "provider": "gpt-image",
        "model": "gpt-image (built-in image_gen)",
        "provider_implementation": "Codex direct built-in image_gen tool",
        "provider_role": (
            "GPT Image semantic Pixel Master redraw" if method == "D1" or stage == "stage2"
            else "GPT Image semantic stage 1"
        ),
        "source_id": source_id,
        "stage": stage,
        "prompt": prompt,
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "refs": [str(path.resolve()) for path in source_refs],
        "ref_sha256": {str(path.resolve()): sha256_file(path) for path in source_refs},
        "tool_saved_path": str(saved_path),
        "out": str(destination.resolve()),
        "raw": str(destination.resolve()),
        "raw_sha256": digest,
        "tool": "built-in image_gen",
        "generation_mode": "direct_gpt_image_tool",
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    provenance_path = gpt_dir / "provenance.json"
    provenance = json.loads(provenance_path.read_text(encoding="utf-8")) if provenance_path.exists() else {
        "method": method,
        "source_id": source_id,
        "source_sha256": sha256_file(source),
        "semantic_generation": None,
        "intermediate_generation": None,
    }
    field = "semantic_generation" if method == "D1" or stage == "stage2" else "intermediate_generation"
    provenance[field] = generation
    write_json(provenance_path, provenance)
    print(f"Recorded {method} {source_id} {stage}: {destination} ({digest})", flush=True)
    return destination


def prepare_reused_smoke_assets() -> None:
    smoke_manifest = json.loads((SMOKE_ROOT / "run_manifest.json").read_text(encoding="utf-8"))
    for source_id in REUSED_SOURCE_IDS:
        source_hash = sha256_file(_source(source_id))
        if smoke_manifest.get("fixture_sha256", {}).get(source_id) != source_hash:
            raise ValueError(f"Smoke semantic source hash does not match immutable fixture {source_id}")
        for method in METHODS:
            original_path = SMOKE_ROOT / "provenance" / method / f"{source_id}.json"
            original = json.loads(original_path.read_text(encoding="utf-8"))
            if original.get("source_sha256") != source_hash:
                raise ValueError(f"GPT Image provenance source hash mismatch: {original_path}")
            gpt_dir = _gpt_dir(method, source_id)
            gpt_dir.mkdir(parents=True, exist_ok=True)
            if method == "D1":
                generation = original["semantic_generation"]
                raw_source = Path(generation["raw"])
                destination = gpt_dir / "raw.png"
                _copy_verified(raw_source, destination, generation["raw_sha256"])
                payload = {
                    "method": method,
                    "source_id": source_id,
                    "source_sha256": source_hash,
                    "semantic_generation": {**generation, "raw": str(destination), "out": str(destination)},
                    "reused_from": str(original_path.resolve()),
                    "reused_from_run": str(SMOKE_ROOT.resolve()),
                }
            else:
                intermediate = original["intermediate_generation"]
                semantic = original["semantic_generation"]
                stage1_path = Path(intermediate["raw"])
                stage2_path = Path(semantic["raw"])
                stage1_dest = gpt_dir / "stage1.png"
                stage2_dest = gpt_dir / "stage2.png"
                _copy_verified(stage1_path, stage1_dest, intermediate["raw_sha256"])
                _copy_verified(stage2_path, stage2_dest, semantic["raw_sha256"])
                payload = {
                    "method": method,
                    "source_id": source_id,
                    "source_sha256": source_hash,
                    "intermediate_generation": {**intermediate, "raw": str(stage1_dest), "out": str(stage1_dest)},
                    "semantic_generation": {**semantic, "raw": str(stage2_dest), "out": str(stage2_dest)},
                    "reused_from": str(original_path.resolve()),
                    "reused_from_run": str(SMOKE_ROOT.resolve()),
                }
            provenance_path = gpt_dir / "provenance.json"
            if provenance_path.exists():
                existing = json.loads(provenance_path.read_text(encoding="utf-8"))
                if existing.get("source_sha256") != source_hash:
                    raise ValueError(f"Refusing to replace different provenance: {provenance_path}")
            write_json(provenance_path, payload)


def _semantic_and_intermediate(method: str, source_id: str) -> tuple[Path, Path | None, dict[str, Any]]:
    gpt_dir = _gpt_dir(method, source_id)
    provenance_path = gpt_dir / "provenance.json"
    if not provenance_path.is_file():
        raise FileNotFoundError(f"Missing GPT Image provenance: {provenance_path}")
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    if provenance.get("source_sha256") != sha256_file(_source(source_id)):
        raise ValueError(f"GPT Image source hash mismatch: {provenance_path}")
    semantic_record = provenance.get("semantic_generation")
    if not isinstance(semantic_record, dict):
        raise ValueError(f"Missing semantic generation provenance: {provenance_path}")
    semantic_raw = Path(semantic_record["raw"])
    if not semantic_raw.is_file():
        raise FileNotFoundError(f"Semantic raw image is missing: {semantic_raw}")
    if sha256_file(semantic_raw) != semantic_record.get("raw_sha256"):
        raise ValueError(f"Semantic image SHA-256 mismatch: {semantic_raw}")
    method_dir = RUN_ROOT / "methods" / method / source_id
    semantic_path = method_dir / "semantic" / f"{source_id}.png"
    _copy_verified(semantic_raw, semantic_path, semantic_record["raw_sha256"])
    intermediate_path: Path | None = None
    if method == "D2":
        intermediate_record = provenance.get("intermediate_generation")
        if not isinstance(intermediate_record, dict):
            raise ValueError(f"Missing D2 stage1 provenance: {provenance_path}")
        stage1_raw = Path(intermediate_record["raw"])
        if sha256_file(stage1_raw) != intermediate_record.get("raw_sha256"):
            raise ValueError(f"D2 intermediate SHA-256 mismatch: {stage1_raw}")
        intermediate_path = method_dir / "intermediate" / f"{source_id}.png"
        _copy_verified(stage1_raw, intermediate_path, intermediate_record["raw_sha256"])
    return semantic_path, intermediate_path, provenance


def preflight_assets() -> None:
    prepare_reused_smoke_assets()
    for method in METHODS:
        for source_id in SOURCE_IDS:
            semantic_path, _, provenance = _semantic_and_intermediate(method, source_id)
            provider = provenance["semantic_generation"].get("provider")
            if provider != "gpt-image":
                raise ValueError(f"Non-GPT semantic provider rejected for {method}/{source_id}: {provider}")
            image = _open_rgba(semantic_path)
            quality = evaluate_semantic_source(image)
            print(
                f"Preflight {method} {source_id}: provider={provider}; size={image.size}; "
                f"semantic_quality={quality.status}",
                flush=True,
            )


def _run_one(source_id: str, method: str) -> dict[str, Any]:
    source_path = _source(source_id)
    manifest_path = RUN_ROOT / "ifm" / source_id / "identity_feature_manifest.json"
    manifest = manifest_from_json(manifest_path)
    if manifest.source_id != source_id or not manifest.features:
        raise ValueError(f"Invalid IFM for {source_id}: {manifest_path}")
    method_dir = RUN_ROOT / "methods" / method / source_id
    report_path = method_dir / "report.json"
    if report_path.is_file():
        report = json.loads(report_path.read_text(encoding="utf-8"))
        prior_resolution = report.get("resolution", {})
        if prior_resolution.get("root_cause") != "IDENTITY_REVIEW_UNAVAILABLE":
            print(f"Audit {method} {source_id}: reusing completed report {report['status']}", flush=True)
            return report
        print(f"Audit {method} {source_id}: retrying prior fail-closed reviewer timeout", flush=True)
    semantic_path, intermediate_path, provenance = _semantic_and_intermediate(method, source_id)
    logical_path = method_dir / "logical" / f"{source_id}.png"
    preview_path = method_dir / "logical" / f"{source_id}.preview-4x.png"
    options = SemanticPseOptions()
    semantic_provider = provenance["semantic_generation"]
    intermediate = None
    if intermediate_path is not None:
        intermediate = {
            "path": str(intermediate_path.resolve()),
            "provider": provenance["intermediate_generation"],
        }
    accepted, report, selected = _run_auto(
        source_path=source_path,
        semantic_path=semantic_path,
        logical_path=logical_path,
        preview_path=preview_path,
        report_path=report_path,
        semantic_provider=semantic_provider,
        manifest=manifest,
        options=options,
        strategy=f"semantic_{method.lower()}_auto_resolution_audit",
        intermediate=intermediate,
        audit=True,
    )
    report["source_id"] = source_id
    report["method"] = method
    report["ifm_provenance"] = json.loads((RUN_ROOT / "ifm" / source_id / "identity_feature_manifest_provenance.json").read_text(encoding="utf-8"))
    report["identity_manifest_path"] = str(manifest_path.resolve())
    report["accepted_sha256"] = sha256_file(accepted) if accepted else None
    write_json(report_path, report)
    print(f"Audit {method} {source_id}: {report['status']} selected={selected}", flush=True)
    return report


def _write_csv(path: Path, header: list[str], rows: list[list[Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(header)
        writer.writerows(rows)


def _rgba_thumbnail(path: Path, box: tuple[int, int], *, nearest: bool = False) -> Image.Image:
    with Image.open(path) as opened:
        image = opened.convert("RGBA")
    resampling = Image.Resampling.NEAREST if nearest else Image.Resampling.LANCZOS
    image.thumbnail(box, resampling)
    return image


def _open_rgba(path: Path) -> Image.Image:
    with Image.open(path) as opened:
        return opened.convert("RGBA")


def _draw_contained(canvas: Image.Image, image: Image.Image, x: int, y: int, box: int) -> None:
    background = Image.new("RGBA", (box, box), (246, 246, 246, 255))
    offset = ((box - image.width) // 2, (box - image.height) // 2)
    background.alpha_composite(image, offset)
    canvas.alpha_composite(background, (x, y))


def _font(size: int = 22) -> ImageFont.ImageFont:
    try:
        return ImageFont.truetype("arial.ttf", size)
    except OSError:
        return ImageFont.load_default()


def _write_sheets(reports: dict[str, dict[str, Any]]) -> None:
    sheet_root = RUN_ROOT / "sheets"
    for relative in ("by_source", "semantic_audit", "resolution_candidates/D1", "resolution_candidates/D2", "ifm_audit"):
        (sheet_root / relative).mkdir(parents=True, exist_ok=True)
    font = _font()
    small = _font(17)
    for source_id in SOURCE_IDS:
        source_path = _source(source_id)
        source_cell = 720
        master_previews: dict[str, Path] = {}
        for method in METHODS:
            report = reports.get(f"{method}/{source_id}", {})
            logical_path = report.get("accepted_path")
            preview_path = Path(logical_path).with_name(f"{source_id}.preview-4x.png") if logical_path else None
            if preview_path and preview_path.is_file():
                master_previews[method] = preview_path
        master_cell = max(
            [1040] + [max(_open_rgba(path).size) + 36 for path in master_previews.values()]
        )
        header = 72
        by_source = Image.new("RGBA", (source_cell + master_cell * 2, header + master_cell), "white")
        draw = ImageDraw.Draw(by_source)
        labels = (("Source fixture", 0), ("D1 selected logical master · 4× nearest", source_cell), ("D2 selected logical master · 4× nearest", source_cell + master_cell))
        for label, x in labels:
            draw.text((x + 18, 18), label, fill=(20, 20, 20), font=font)
        src_thumb = _rgba_thumbnail(source_path, (source_cell - 36, master_cell - 36))
        _draw_contained(by_source, src_thumb, 18, header + 18, source_cell - 36)
        for method, x in (("D1", source_cell), ("D2", source_cell + master_cell)):
            report = reports.get(f"{method}/{source_id}", {})
            if method in master_previews:
                preview = _open_rgba(master_previews[method])
                _draw_contained(by_source, preview, x + 18, header + 18, master_cell - 36)
                status = f"{report.get('status')} · H{report.get('logical', {}).get('target_height')}"
            else:
                status = f"NO ACCEPTED MASTER · {report.get('status', 'NOT_RUN')}"
            draw.text((x + 18, header + master_cell - 38), status, fill=(110, 20, 20), font=small)
        by_source.save(sheet_root / "by_source" / f"{source_id}.png")

        semantic_sheet = Image.new("RGBA", (3 * 720, 900), "white")
        draw = ImageDraw.Draw(semantic_sheet)
        columns = [("Source", source_path)]
        for method in METHODS:
            semantic = RUN_ROOT / "methods" / method / source_id / "semantic" / f"{source_id}.png"
            columns.append((f"{method} semantic", semantic))
        for index, (label, path) in enumerate(columns):
            x = index * 720
            draw.text((x + 18, 16), label, fill=(20, 20, 20), font=font)
            if path.is_file():
                thumb = _rgba_thumbnail(path, (680, 820))
                _draw_contained(semantic_sheet, thumb, x + 20, 60, 680)
            else:
                draw.text((x + 24, 100), "missing", fill=(150, 0, 0), font=font)
        semantic_sheet.save(sheet_root / "semantic_audit" / f"{source_id}.png")

        for method in METHODS:
            report = reports.get(f"{method}/{source_id}", {})
            details = report.get("resolution", {}).get("candidate_details", {})
            preview_paths = {
                height: Path(details[str(height)]["logical_candidate_preview_path"])
                if details.get(str(height), {}).get("logical_candidate_preview_path") else None
                for height in AUTO_LOGICAL_HEIGHTS
            }
            present_previews = [path for path in preview_paths.values() if path and path.is_file()]
            cell = max([1040] + [max(_open_rgba(path).size) + 36 for path in present_previews])
            candidate_sheet = Image.new("RGBA", (len(AUTO_LOGICAL_HEIGHTS) * cell, 72 + cell), "white")
            draw = ImageDraw.Draw(candidate_sheet)
            for index, height in enumerate(AUTO_LOGICAL_HEIGHTS):
                x = index * cell
                detail = details.get(str(height), {})
                draw.text((x + 18, 16), f"{method} · H{height} · {detail.get('status', 'NOT_REQUIRED')}", fill=(20, 20, 20), font=font)
                preview_path = preview_paths[height]
                if preview_path and preview_path.is_file():
                    preview = _open_rgba(preview_path)
                    _draw_contained(candidate_sheet, preview, x + 18, 70, cell - 36)
                if detail:
                    validation = detail.get("logical_validation", {}).get("status", "NO_VALIDATION")
                    draw.text((x + 18, 72 + cell - 25), f"logical validator: {validation}", fill=(60, 60, 60), font=small)
            candidate_sheet.save(sheet_root / "resolution_candidates" / method / f"{source_id}.png")

        ifm_path = RUN_ROOT / "ifm" / source_id / "identity_feature_manifest.json"
        if ifm_path.is_file():
            manifest = json.loads(ifm_path.read_text(encoding="utf-8"))
            ifm_sheet = Image.new("RGBA", (1200, 900), "white")
            src = _rgba_thumbnail(source_path, (680, 800))
            _draw_contained(ifm_sheet, src, 20, 20, 680)
            draw = ImageDraw.Draw(ifm_sheet)
            with Image.open(source_path) as opened:
                width, height = opened.size
            x0, y0 = 20 + (680 - src.width) // 2, 20 + (800 - src.height) // 2
            scale_x, scale_y = src.width / width, src.height / height
            for index, feature in enumerate(manifest.get("features", [])):
                region = feature.get("region") or {}
                box = (
                    x0 + int(region.get("x", 0) * width * scale_x),
                    y0 + int(region.get("y", 0) * height * scale_y),
                    x0 + int((region.get("x", 0) + region.get("w", 0)) * width * scale_x),
                    y0 + int((region.get("y", 0) + region.get("h", 0)) * height * scale_y),
                )
                color = (255, 40 + index * 23 % 150, 20, 255)
                draw.rectangle(box, outline=color, width=3)
            draw.text((725, 20), f"IFM draft · {source_id}", fill=(20, 20, 20), font=font)
            y = 70
            for feature in manifest.get("features", []):
                heading = f"{feature['importance']} · {feature['id']}"
                draw.text((725, y), heading[:52], fill=(145, 35, 25), font=small)
                y += 22
                for line in textwrap.wrap(str(feature["label"]), width=43):
                    draw.text((740, y), line, fill=(20, 20, 20), font=small)
                    y += 20
                y += 8
                if y > 890:
                    break
            ifm_sheet.save(sheet_root / "ifm_audit" / f"{source_id}.png")

    overview = Image.new("RGBA", (3 * 600, 3 * 450), "white")
    for index, source_id in enumerate(SOURCE_IDS):
        path = sheet_root / "ifm_audit" / f"{source_id}.png"
        if path.is_file():
            thumbnail = _rgba_thumbnail(path, (600, 450))
            overview.alpha_composite(thumbnail, ((index % 3) * 600, (index // 3) * 450))
    overview.save(sheet_root / "ifm_audit" / "overview.png")


def build_reports(reports: dict[str, dict[str, Any]]) -> None:
    summary_rows: list[list[Any]] = []
    matrix_rows: list[list[Any]] = []
    feature_rows: list[list[Any]] = []
    for method in METHODS:
        for source_id in SOURCE_IDS:
            key = f"{method}/{source_id}"
            report = reports.get(key)
            if not report:
                summary_rows.append([source_id, method, "NOT_RUN", None, None, None, None, None])
                continue
            resolution = report.get("resolution", {})
            selected = resolution.get("selected")
            semantic = report.get("semantic_preservation", {})
            logical = report.get("logical", {})
            summary_rows.append([
                source_id, method, report.get("status"), selected,
                semantic.get("status"), resolution.get("root_cause"),
                report.get("accepted_path"), report.get("accepted_sha256"),
            ])
            details = resolution.get("candidate_details", {})
            for height in AUTO_LOGICAL_HEIGHTS:
                item = details.get(str(height), {})
                info = item.get("information_loss") or {}
                validation = item.get("logical_validation") or {}
                matrix_rows.append([
                    source_id, method, height, item.get("status", "NOT_REQUIRED"),
                    validation.get("status"), item.get("identity_loss_index"),
                    info.get("status"), height == selected, item.get("cleanup_mutated_dimensions"),
                ])
                review = item.get("identity_review") or {}
                for feature in info.get("feature_results", []):
                    feature_rows.append([
                        source_id, method, "logical", height, feature.get("id"), feature.get("label"),
                        feature.get("importance"), feature.get("state"), feature.get("reason"),
                        next((v.get("confidence") for v in review.get("features", []) if v.get("id") == feature.get("id")), None),
                        review.get("status"), review.get("session_id"),
                    ])
            for feature in semantic.get("feature_results", []):
                review = semantic.get("identity_review") or {}
                feature_rows.append([
                    source_id, method, "semantic", None, feature.get("id"), feature.get("label"),
                    feature.get("importance"), feature.get("state"), feature.get("reason"),
                    next((v.get("confidence") for v in review.get("features", []) if v.get("id") == feature.get("id")), None),
                    review.get("status"), review.get("session_id"),
                ])

    _write_csv(
        RUN_ROOT / "logical_master_results.csv",
        ["source_id", "method", "status", "selected_height", "semantic_preservation_status", "root_cause", "accepted_path", "accepted_sha256"],
        summary_rows,
    )
    _write_csv(
        RUN_ROOT / "resolution_matrix.csv",
        ["source_id", "method", "logical_height", "candidate_status", "validator_status", "identity_loss_index", "information_loss_status", "selected", "cleanup_mutated_dimensions"],
        matrix_rows,
    )
    _write_csv(
        RUN_ROOT / "identity_feature_results.csv",
        ["source_id", "method", "stage", "logical_height", "feature_id", "label", "importance", "state", "reason", "review_confidence", "review_status", "review_session_id"],
        feature_rows,
    )
    _write_csv(RUN_ROOT / "human_scores.csv", ["source_id", "method", "score", "reviewer", "notes"], [])

    source_hashes = {source_id: sha256_file(_source(source_id)) for source_id in SOURCE_IDS}
    manifest = {
        "kind": "sprite-studio-auto-resolution-identity-audit",
        "version": 1,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "sources": list(SOURCE_IDS),
        "methods": list(METHODS),
        "provider_policy": "GPT Image only for D1/D2 semantic redraw; no Grok fallback",
        "identity_review": "Codex multimodal IFM review; semantic gate then one side-by-side candidate-grid review per method/source",
        "candidate_heights": list(AUTO_LOGICAL_HEIGHTS),
        "palette_size": 48,
        "resize_rescue": False,
        "threshold_relaxation": False,
        "human_scores_blank": True,
        "automatic_visual_winner": False,
        "hard_case": {"source_id": "R08", "label": "hard case; evaluate separately"},
        "fixture_sha256": source_hashes,
        "fixture_paths": {source_id: str(_source(source_id).resolve()) for source_id in SOURCE_IDS},
        "reports": {key: str((RUN_ROOT / "methods" / key.split("/")[0] / key.split("/")[1] / "report.json").resolve()) for key in reports},
    }
    write_json(RUN_ROOT / "run_manifest.json", manifest)
    write_json(RUN_ROOT / "auto_resolution_report.json", {"run_manifest": manifest, "results": reports})
    _write_sheets(reports)
    _write_summary(reports)


def _write_summary(reports: dict[str, dict[str, Any]]) -> None:
    counts: dict[str, int] = {}
    selected: dict[str, dict[int, int]] = {method: {} for method in METHODS}
    for report in reports.values():
        status = str(report.get("status", "NOT_RUN"))
        counts[status] = counts.get(status, 0) + 1
        method = report.get("method")
        height = report.get("resolution", {}).get("selected")
        if method in selected and height is not None:
            selected[method][height] = selected[method].get(height, 0) + 1
    lines = [
        "# Auto Resolution R00–R08 identity audit",
        "",
        "D1/D2 semantic inputs use GPT Image only. No Grok fallback, resize rescue, threshold relaxation, or automatic visual winner declaration was used.",
        "R08 is recorded separately as the hard case. Human scores remain blank pending direct review.",
        "",
        "## Status counts",
        "",
    ]
    lines.extend(f"- {status}: {count}" for status, count in sorted(counts.items()))
    lines.extend(["", "## Selected logical heights", ""])
    for method in METHODS:
        distribution = ", ".join(f"{height}px: {count}" for height, count in sorted(selected[method].items())) or "none"
        lines.append(f"- {method}: {distribution}")
    lines.extend([
        "",
        "## Manual gate assessment",
        "",
        "Pending visual inspection of `sheets/by_source/`, `sheets/resolution_candidates/`, `sheets/semantic_audit/`, and `sheets/ifm_audit/`. Do not treat the model's identity-review response as human scoring.",
        "",
        "## Full production recommendation",
        "",
        "STOP pending manual confirmation that IFM coverage is accurate and that the candidate-grid gate agrees with visible identity retention. No human score or visual winner has been entered.",
    ])
    (RUN_ROOT / "auto_resolution_audit_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def pilot_candidate_grid(source_id: str, method: str) -> None:
    report_path = RUN_ROOT / "methods" / method / source_id / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    details = report.get("resolution", {}).get("candidate_details", {})
    candidates: dict[int, Image.Image] = {}
    for height in AUTO_LOGICAL_HEIGHTS:
        logical_path = details.get(str(height), {}).get("logical_candidate_path")
        if logical_path and Path(logical_path).is_file():
            candidates[height] = _open_rgba(Path(logical_path))
    if not candidates:
        raise ValueError(f"No validated logical candidates available for {method}/{source_id}")
    manifest = manifest_from_json(RUN_ROOT / "ifm" / source_id / "identity_feature_manifest.json")
    with Image.open(_source(source_id)) as opened:
        source = opened.convert("RGBA")
    results = review_identity_candidate_grid(
        source,
        candidates,
        manifest,
        stage=f"pilot-{method}-candidate-grid",
        workdir=RUN_ROOT / "methods" / method / source_id / "identity-review-pilot",
    )
    payload = {str(height): result for height, result in results.items()}
    write_json(RUN_ROOT / "methods" / method / source_id / "candidate_grid_pilot.json", payload)
    print(json.dumps({
        str(height): {
            "status": result.get("status"),
            "elapsed_seconds": result.get("elapsed_seconds"),
            "model": result.get("model"),
            "error": result.get("error"),
        }
        for height, result in results.items()
    }, ensure_ascii=False, indent=2), flush=True)


def run_audit() -> None:
    preflight_assets()
    if not (RUN_ROOT / "_gpt" / "D1" / "R01" / "provenance.json").is_file():
        raise FileNotFoundError("Record the verified native image_gen D1 R01 output first.")
    reports: dict[str, dict[str, Any]] = {}
    for source_id in SOURCE_IDS:
        for method in METHODS:
            try:
                reports[f"{method}/{source_id}"] = _run_one(source_id, method)
            except Exception as exc:
                error = {
                    "source_id": source_id,
                    "method": method,
                    "status": "FAIL_AUDIT_EXECUTION",
                    "error": f"{type(exc).__name__}: {exc}"[:2000],
                }
                reports[f"{method}/{source_id}"] = error
                print(f"Audit {method} {source_id}: ERROR {error['error']}", flush=True)
    build_reports(reports)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    ifm_parser = commands.add_parser("generate-ifms")
    ifm_parser.add_argument("--sources", default=",".join(SOURCE_IDS))
    record = commands.add_parser("record-generated")
    record.add_argument("--method", choices=METHODS, required=True)
    record.add_argument("--source-id", choices=SOURCE_IDS, required=True)
    record.add_argument("--stage", choices=("raw", "stage1", "stage2"), required=True)
    record.add_argument("--saved-path", type=Path, required=True)
    commands.add_parser("preflight")
    pilot = commands.add_parser("pilot-candidate-grid")
    pilot.add_argument("--source-id", choices=SOURCE_IDS, default="R00")
    pilot.add_argument("--method", choices=METHODS, default="D1")
    commands.add_parser("run")
    args = parser.parse_args()
    if args.command == "generate-ifms":
        generate_ifms(tuple(item.strip() for item in args.sources.split(",") if item.strip()))
    elif args.command == "record-generated":
        record_generated_image(args.method, args.source_id, args.stage, args.saved_path)
    elif args.command == "preflight":
        preflight_assets()
    elif args.command == "pilot-candidate-grid":
        pilot_candidate_grid(args.source_id, args.method)
    else:
        run_audit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
