# SPDX-License-Identifier: Apache-2.0
"""Normalize wide Grok multi-subject output into a component-row strip.

Grok sometimes follows the subject/layout instruction but returns a 16:9
canvas.  This adapter turns that image into the row contract used by the
component-row extractor: one normalized RGBA cell per expected subject.

The operation is deliberately explicit.  Generation remains the only AI step;
this module only performs deterministic chroma removal, x-profile segmentation,
component cleanup, and cell placement.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from PIL import Image

from sprite_studio.spec.runio import atomic_save_image, atomic_write_text

from ..frames.extract import (
    component_group_image,
    connected_components,
    fit_to_cell,
    remove_chroma_background,
)
from ..frames.segment import segment_strip
from .normalize_quality import NormalizeQualityPolicy, evaluate_subject, resolve_row_result

CHROMA_KEYS = {
    "magenta": (255, 0, 255),
    "green": (0, 255, 0),
}

DEFAULT_KEY_THRESHOLD = 96.0
DEFAULT_FRINGE_KEY_THRESHOLD = 180.0
DEFAULT_FRINGE_DELTA = 18.0
DEFAULT_UNMIX_REACH = 4
DEFAULT_SPILL_MAX_FRACTION = 0.005
DEFAULT_COUNT = 4
DEFAULT_CELL_WIDTH = 256
DEFAULT_CELL_HEIGHT = 256
DEFAULT_SAFE_MARGIN = 24


def parse_chroma_key(value: str) -> tuple[int, int, int]:
    name = value.strip().lower()
    if name in CHROMA_KEYS:
        return CHROMA_KEYS[name]
    text = name.lstrip("#")
    if len(text) == 6:
        try:
            return tuple(int(text[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
        except ValueError:
            pass
    raise ValueError(f"unsupported chroma key {value!r}; use magenta, green, or #RRGGBB")


def _zero_transparent_rgb(image: Image.Image) -> Image.Image:
    """Keep transparent output canonical, including after LANCZOS resampling."""
    image = image.convert("RGBA")
    pixels = image.load()
    for y in range(image.height):
        for x in range(image.width):
            red, green, blue, alpha = pixels[x, y]
            if alpha == 0 and (red or green or blue):
                pixels[x, y] = (0, 0, 0, 0)
    return image


def _parse_margin(value: int | None, fallback: int) -> int:
    return fallback if value is None else value


def _refine_forced_spans(
    image: Image.Image,
    spans: list[tuple[int, int]],
    count: int,
    natural_count: int,
) -> list[tuple[int, int]]:
    """Move DP cuts to the next subject onset when overlapping poses were forced apart.

    A forced DP cut minimizes foreground mass, which can place the boundary a few
    pixels before the next figure's helmet/body.  On a wide Grok sheet that can
    move the previous figure's weapon tip into the next cell.  The correction is
    intentionally limited to forced segmentation; natural gutters are already
    authoritative.  The first strong rise after each DP cut is the stable onset
    signal and is bounded to one quarter of the expected cell width.
    """
    if natural_count == count or len(spans) != count:
        return spans
    # Count solid foreground pixels rather than alpha mass.  Antialiased helmet
    # edges raise weighted mass several columns before the subject actually
    # starts, while the solid-pixel onset is the useful ownership boundary for
    # a weapon overhang.
    alpha = image.getchannel("A").tobytes()
    profile = [
        sum(alpha[y * image.width + x] > 16 for y in range(image.height))
        for x in range(image.width)
    ]
    width = image.width
    expected_width = max(1, width // count)
    max_shift = max(4, expected_width // 4)
    boundaries = [span[1] for span in spans[:-1]]
    refined: list[int] = []
    for boundary in boundaries:
        lo = max(0, boundary - max(8, expected_width // 12))
        valley = min(profile[lo : boundary + 1], default=0.0)
        threshold = max(valley * 1.60, valley + 12.0)
        chosen = boundary
        for x in range(boundary + 1, min(width, boundary + max_shift + 1)):
            previous = profile[x - 1]
            if profile[x] >= threshold and (previous <= 0 or profile[x] >= previous * 1.08):
                chosen = x
                break
        if refined and chosen <= refined[-1]:
            chosen = refined[-1] + 1
        refined.append(chosen)
    edges = [0, *refined, width]
    return [(edges[index], edges[index + 1]) for index in range(count)]


def _leading_overhang_trim(piece: Image.Image, global_top: int, global_bottom: int) -> int:
    """Find a small previous-weapon overhang before a subject's head onset.

    Forced cuts can leave the last few columns of the previous figure connected
    to the next figure.  Those columns usually start materially lower than the
    next figure's head.  Trim only that leading band; the rest of the piece is
    still selected by the normal component cleanup path.
    """
    alpha = piece.getchannel("A").tobytes()
    height = piece.height
    top_limit = global_top + max(8, round((global_bottom - global_top) * 0.10))
    scan_limit = min(piece.width, max(16, piece.width // 5))
    for x in range(scan_limit):
        if any(alpha[y * piece.width + x] > 16 and y <= top_limit for y in range(height)):
            return x
    return 0


def normalize_image(
    image: Image.Image,
    chroma_key: tuple[int, int, int],
    *,
    count: int = DEFAULT_COUNT,
    cell_width: int = DEFAULT_CELL_WIDTH,
    cell_height: int = DEFAULT_CELL_HEIGHT,
    safe_margin_x: int = DEFAULT_SAFE_MARGIN,
    safe_margin_y: int = DEFAULT_SAFE_MARGIN,
    key_threshold: float = DEFAULT_KEY_THRESHOLD,
    fringe_key_threshold: float = DEFAULT_FRINGE_KEY_THRESHOLD,
    fringe_delta: float = DEFAULT_FRINGE_DELTA,
    unmix_reach: int = DEFAULT_UNMIX_REACH,
    spill_max_fraction: float = DEFAULT_SPILL_MAX_FRACTION,
    resample: str = "nearest",
    align_x: str = "foot-centroid",
    align_y: str = "bottom",
    quality: NormalizeQualityPolicy | None = None,
) -> tuple[Image.Image, dict[str, Any]]:
    """Return ``(normalized_row, diagnostic_report)`` for one wide image.

    ``quality`` gates cell acceptance (Subject Validity Gate + Row-Level
    Acceptance Gate — see ``normalize_quality.py``). It never raises: a
    malformed row still produces its normalized preview and a report with
    ``report["result"] in {"pass", "recovered_with_warning", "fail"}`` so the
    rejected output can be inspected (directive §7) instead of vanishing.
    Callers that must not promote a failed row downstream (Studio's
    ``spritegen_bridge.normalize_state``) check ``report["result"]``
    themselves. Passing ``quality=None`` uses ``NormalizeQualityPolicy.default()``.
    """
    quality = quality or NormalizeQualityPolicy.default()
    if count < 1:
        raise ValueError("count must be positive")
    if cell_width < 1 or cell_height < 1:
        raise ValueError("cell width/height must be positive")
    if safe_margin_x < 0 or safe_margin_y < 0:
        raise ValueError("safe margins must be zero or positive")
    if safe_margin_x * 2 >= cell_width or safe_margin_y * 2 >= cell_height:
        raise ValueError("safe margins must leave a positive usable cell area")
    if fringe_key_threshold < key_threshold:
        raise ValueError("fringe-key-threshold must be greater than or equal to key-threshold")
    if unmix_reach < 0 or spill_max_fraction < 0:
        raise ValueError("unmix-reach and spill-max-fraction must be zero or positive")
    if resample not in {"nearest", "lanczos", "kcentroid"}:
        raise ValueError("resample must be nearest, lanczos, or kcentroid")

    cleaned = remove_chroma_background(
        image.convert("RGBA"),
        chroma_key,
        key_threshold,
        fringe_key_threshold,
        fringe_delta,
        unmix_reach=unmix_reach,
        spill_max_fraction=spill_max_fraction,
    )
    spans, natural_count = segment_strip(cleaned, count)
    if len(spans) != count:
        raise ValueError(
            f"could not find {count} subject spans (detected {natural_count}, usable {len(spans)}); "
            "inspect the source or change --count"
        )
    spans = _refine_forced_spans(cleaned, spans, count, natural_count)
    global_bbox = cleaned.getbbox()
    global_top, global_bottom = (global_bbox[1], global_bbox[3]) if global_bbox else (0, cleaned.height)

    forced = natural_count != count
    subject_policy = quality.subject_policy_for(forced=forced)

    fit = {"resample": resample, "align_x": align_x, "align_y": align_y}
    cells: list[Image.Image] = []
    subject_reports: list[dict[str, Any]] = []
    for index, (left, right) in enumerate(spans):
        piece = cleaned.crop((left, 0, right, cleaned.height))
        leading_trim = 0
        if natural_count != count and index > 0:
            leading_trim = _leading_overhang_trim(piece, global_top, global_bottom)
            if leading_trim:
                piece = piece.crop((leading_trim, 0, piece.width, piece.height))
        components = connected_components(piece)
        if not components:
            raise ValueError(f"subject span {index} is empty after component cleanup: x={left}:{right}")
        main_component = max(components, key=lambda component: component["area"])
        subject = component_group_image(piece, [main_component])
        source_bbox = subject.getbbox()
        assert source_bbox is not None
        cell = fit_to_cell(
            subject,
            cell_width,
            cell_height,
            safe_margin_x,
            safe_margin_y,
            fit,
        )
        cells.append(cell)
        validity = evaluate_subject(
            cell,
            cell_width=cell_width,
            cell_height=cell_height,
            safe_margin_x=safe_margin_x,
            safe_margin_y=safe_margin_y,
            chroma_key=chroma_key,
            # fringe_key_threshold, not key_threshold: remove_chroma_background
            # already erases anything within key_threshold of the key, so a
            # pixel surviving as opaque foreground is by definition beyond
            # key_threshold. Residue that leaked through keying (still within
            # the broader keyed-color family, out to the fringe boundary) is
            # what this metric needs to catch.
            chroma_residual_threshold=fringe_key_threshold,
            edge_margin=max(1, safe_margin_x),
            policy=subject_policy,
        )
        subject_reports.append(
            {
                "index": index,
                "span": [left, right],
                "leading_trim": leading_trim,
                "source_bbox": list(source_bbox),
                "source_size": [source_bbox[2] - source_bbox[0], source_bbox[3] - source_bbox[1]],
                "cell_bbox": list(cell.getbbox()) if cell.getbbox() else None,
                "used_pixels": sum(cell.getchannel("A").histogram()[1:]),
                "component_count": len(components),
                "dropped_components": len(components) - 1,
                "valid": validity["valid"],
                "reasons": validity["reasons"],
                "metrics": validity["metrics"],
            }
        )

    valid_subjects = sum(1 for subject in subject_reports if subject["valid"])
    result = resolve_row_result(valid_subjects, count, forced=forced)

    output = Image.new("RGBA", (cell_width * count, cell_height), (0, 0, 0, 0))
    for index, cell in enumerate(cells):
        output.alpha_composite(cell, (index * cell_width, 0))
    output = _zero_transparent_rgb(output)
    report = {
        "kind": "sprite-studio-grok-row-normalization",
        "source_size": list(cleaned.size),
        "output_size": list(output.size),
        "count": count,
        "cell": {"width": cell_width, "height": cell_height},
        "safe_margin": {"x": safe_margin_x, "y": safe_margin_y},
        "chroma_key": {"rgb": list(chroma_key)},
        "segmentation": {
            "natural_count": natural_count,
            "forced": forced,
            "spans": [list(span) for span in spans],
        },
        "subjects": subject_reports,
        "result": result,
        "expected_subjects": count,
        "valid_subjects": valid_subjects,
        "resample": resample,
        "align_x": align_x,
        "align_y": align_y,
    }
    return output, report


def run(
    *,
    input: Path,
    out: Path,
    chroma_key: str = "green",
    count: int = DEFAULT_COUNT,
    cell_width: int = DEFAULT_CELL_WIDTH,
    cell_height: int = DEFAULT_CELL_HEIGHT,
    safe_margin: int | None = DEFAULT_SAFE_MARGIN,
    safe_margin_x: int | None = None,
    safe_margin_y: int | None = None,
    key_threshold: float = DEFAULT_KEY_THRESHOLD,
    fringe_key_threshold: float = DEFAULT_FRINGE_KEY_THRESHOLD,
    fringe_delta: float = DEFAULT_FRINGE_DELTA,
    unmix_reach: int = DEFAULT_UNMIX_REACH,
    spill_max_fraction: float = DEFAULT_SPILL_MAX_FRACTION,
    resample: str = "nearest",
    align_x: str = "foot-centroid",
    align_y: str = "bottom",
    background: str = "transparent",
    report: Path | None = None,
    quality: NormalizeQualityPolicy | None = None,
    quality_config: Path | None = None,
) -> int:
    input = input.expanduser().resolve()
    out = out.expanduser().resolve()
    if not input.is_file():
        raise SystemExit(f"normalize-grok-row: input image not found: {input}")
    if background not in {"transparent", "chroma"}:
        raise SystemExit("normalize-grok-row: background must be transparent or chroma")
    if quality is not None and quality_config is not None:
        raise SystemExit("normalize-grok-row: pass either quality or quality_config, not both")
    if quality_config is not None:
        quality_config = quality_config.expanduser().resolve()
        try:
            quality = NormalizeQualityPolicy.from_dict(
                json.loads(quality_config.read_text(encoding="utf-8"))
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise SystemExit(f"normalize-grok-row: invalid --quality-config {quality_config}: {exc}") from exc
    try:
        key = parse_chroma_key(chroma_key)
        with Image.open(input) as opened:
            normalized, payload = normalize_image(
                opened,
                key,
                count=count,
                cell_width=cell_width,
                cell_height=cell_height,
                safe_margin_x=_parse_margin(safe_margin_x, safe_margin or 0),
                safe_margin_y=_parse_margin(safe_margin_y, safe_margin or 0),
                key_threshold=key_threshold,
                fringe_key_threshold=fringe_key_threshold,
                fringe_delta=fringe_delta,
                unmix_reach=unmix_reach,
                spill_max_fraction=spill_max_fraction,
                resample=resample,
                align_x=align_x,
                align_y=align_y,
                quality=quality,
            )
    except (OSError, ValueError) as exc:
        raise SystemExit(f"normalize-grok-row: {exc}") from exc

    if background == "chroma":
        chroma_output = Image.new("RGB", normalized.size, key)
        chroma_output.paste(normalized.convert("RGB"), mask=normalized.getchannel("A"))
        normalized = chroma_output
    atomic_save_image(normalized, out)
    payload["input"] = str(input)
    payload["output"] = str(out)
    payload["background"] = background
    if report:
        report = report.expanduser().resolve()
        atomic_write_text(report, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        payload["report"] = str(report)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--input", required=True, type=Path, help="wide Grok PNG (for example 1280x720)")
    parser.add_argument("--out", required=True, type=Path, help="normalized row PNG")
    parser.add_argument("--chroma-key", default="green", help="magenta, green, or #RRGGBB")
    parser.add_argument("--count", type=int, default=DEFAULT_COUNT, help="number of subjects/row cells")
    parser.add_argument("--cell-width", type=int, default=DEFAULT_CELL_WIDTH)
    parser.add_argument("--cell-height", type=int, default=DEFAULT_CELL_HEIGHT)
    parser.add_argument("--safe-margin", type=int, default=DEFAULT_SAFE_MARGIN)
    parser.add_argument("--safe-margin-x", type=int)
    parser.add_argument("--safe-margin-y", type=int)
    parser.add_argument("--key-threshold", type=float, default=DEFAULT_KEY_THRESHOLD)
    parser.add_argument("--fringe-key-threshold", type=float, default=DEFAULT_FRINGE_KEY_THRESHOLD)
    parser.add_argument("--fringe-delta", type=float, default=DEFAULT_FRINGE_DELTA)
    parser.add_argument("--unmix-reach", type=int, default=DEFAULT_UNMIX_REACH)
    parser.add_argument("--spill-max-fraction", type=float, default=DEFAULT_SPILL_MAX_FRACTION)
    parser.add_argument("--resample", choices=("nearest", "lanczos", "kcentroid"), default="nearest")
    parser.add_argument("--align-x", choices=("foot-centroid", "centroid", "alpha-centroid", "bbox-center"), default="foot-centroid")
    parser.add_argument("--align-y", choices=("bottom", "center"), default="bottom")
    parser.add_argument("--background", choices=("transparent", "chroma"), default="transparent")
    parser.add_argument("--report", type=Path)
    parser.add_argument(
        "--quality-config",
        type=Path,
        help="JSON normalize_quality policy (Subject Validity / Row-Level Acceptance Gate "
        "thresholds); default is a conservative built-in policy",
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    add_arguments(parser)
    return parser


def main(argv: list[str] | None = None) -> int:
    return run(**vars(_build_parser().parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
