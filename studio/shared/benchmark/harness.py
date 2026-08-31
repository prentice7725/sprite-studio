# SPDX-License-Identifier: MIT
"""Synthetic degradation benchmark harness (spec §9).

    ground truth asset -> synthetic degradation -> refine/repair -> compare

This is the objective standard the spec asks for (§9.5: *"this benchmark
becomes the objective basis for algorithm improvement"*, §16.10: *"do not
regress algorithm changes past the benchmark"*). Without it, "the refine got
better" is an opinion formed by looking at one sprite.

Two things make it usable as a gate rather than a demo:

* **Deterministic.** Fixed seeds, fixed ground truth, no RNG in the pipeline
  itself. A score change means the algorithm changed.
* **Comparable.** ``compare_runs`` diffs two result sets and names which cases
  moved, so a change that improves thin-feature recovery while quietly wrecking
  seam integrity cannot pass as an improvement.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence

import numpy as np
from PIL import Image

from studio.shared.config import RefineSettings, load_refine_settings

from .degrade import degrade
from .metrics import sprite_metrics, static_metrics, temporal_consistency


@dataclass(frozen=True)
class BenchmarkCase:
    name: str
    mode: str
    frames: tuple[Image.Image, ...]
    degradations: tuple[str, ...]
    strength: float = 1.0
    upscale: int = 6
    tileable: bool = False


@dataclass(frozen=True)
class CaseResult:
    name: str
    mode: str
    degradations: tuple[str, ...]
    metrics: dict[str, Any]
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "case": self.name,
            "mode": self.mode,
            "degradations": list(self.degradations),
            "metrics": self.metrics,
            "warnings": list(self.warnings),
        }


@dataclass
class BenchmarkReport:
    results: list[CaseResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "asset-studio-benchmark",
            "version": 1,
            "cases": [result.to_dict() for result in self.results],
            "summary": self.summary(),
        }

    def summary(self) -> dict[str, Any]:
        sprite = [item for item in self.results if item.mode == "sprite"]
        static = [item for item in self.results if item.mode == "static"]
        return {
            "cases": len(self.results),
            "sprite_mean_iou": _mean(sprite, ("silhouette", "iou")),
            "sprite_mean_thin_recovery": _mean(sprite, ("thin_feature", "recovered")),
            "static_mean_palette_retained": _mean(static, ("palette", "retained")),
            "static_mean_delta_e": _mean(static, ("color", "mean_delta_e")),
        }

    def write(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return path


def _mean(results: Sequence[CaseResult], keys: tuple[str, str]) -> float | None:
    values = []
    for result in results:
        section = result.metrics.get(keys[0]) or {}
        value = section.get(keys[1])
        if isinstance(value, (int, float)):
            values.append(float(value))
    return round(float(np.mean(values)), 6) if values else None


def upscale(image: Image.Image, factor: int) -> Image.Image:
    """Nearest-neighbour blow-up — how a generator would have been asked to draw it."""
    return image.convert("RGBA").resize((image.width * factor, image.height * factor), Image.Resampling.NEAREST)


def synthetic_sprite_row(frames: int = 4, size: int = 24, *, seed: int = 11) -> list[Image.Image]:
    """A tiny character with a one-pixel weapon, animated by a small shift.

    Deliberately includes a thin feature and a per-frame offset: those are the
    two properties Sprite Mode's refine is judged on, and ground truth without
    them would grade nothing.
    """
    rng = np.random.default_rng(seed)
    palette = rng.integers(40, 220, (5, 3), dtype=np.uint8)
    row: list[Image.Image] = []
    for index in range(frames):
        image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        pixels = image.load()
        for y in range(size // 4, size - 2):
            for x in range(size // 3, 2 * size // 3):
                color = palette[(x + y + index) % 4]
                pixels[x, y] = (int(color[0]), int(color[1]), int(color[2]), 255)
        blade_x = min(size - 1, 2 * size // 3 + 1 + (index % 2))
        for y in range(2, size // 2):
            pixels[blade_x, y] = (int(palette[4][0]), int(palette[4][1]), int(palette[4][2]), 255)
        row.append(image)
    return row


def synthetic_scene(size: int = 32, *, colors: int = 12, seed: int = 5, tileable: bool = False) -> Image.Image:
    """A flat-palette scene; optionally built so its edges already wrap."""
    rng = np.random.default_rng(seed)
    palette = rng.integers(20, 235, (colors, 3), dtype=np.uint8)
    index = rng.integers(0, colors, (size, size))
    if tileable:
        index[:, -1] = index[:, 0]
        index[-1, :] = index[0, :]
    rgb = palette[index]
    return Image.fromarray(
        np.dstack([rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2], np.full((size, size), 255, np.uint8)]), "RGBA"
    )


def default_cases() -> list[BenchmarkCase]:
    """The standing case set: every degradation each mode is expected to survive."""
    sprite_row = tuple(synthetic_sprite_row())
    scene = synthetic_scene()
    tile = synthetic_scene(seed=9, tileable=True)
    cases: list[BenchmarkCase] = []
    for degradations in (
        ("blur",),
        ("subpixel_offset",),
        ("antialiased_resize",),
        ("pseudo_pixel_alias",),
        ("boundary_bleed",),
        ("thin_feature_loss",),
        ("subpixel_offset", "boundary_bleed"),
    ):
        cases.append(BenchmarkCase(f"sprite:{'+'.join(degradations)}", "sprite", sprite_row, degradations))
    for degradations in (
        ("blur",),
        ("antialiased_resize",),
        ("pseudo_pixel_alias",),
        ("boundary_bleed",),
        ("chroma_contamination",),
    ):
        cases.append(BenchmarkCase(f"static:{'+'.join(degradations)}", "static", (scene,), degradations))
    cases.append(BenchmarkCase("static:tile:boundary_bleed", "static", (tile,), ("boundary_bleed",), tileable=True))
    return cases


SpriteRunner = Callable[[Sequence[Image.Image], RefineSettings], Sequence[Image.Image]]
StaticRunner = Callable[[Image.Image, RefineSettings], Image.Image]


def _default_sprite_runner(frames: Sequence[Image.Image], settings: RefineSettings) -> Sequence[Image.Image]:
    from studio.sprite_mode.refine import SpriteRefineEngine

    width, height = frames[0].size
    output = SpriteRefineEngine(settings).refine(
        frames, state="benchmark", cell_width=width, cell_height=height,
        safe_margin_x=0, safe_margin_y=0,
    )
    return output.logical_frames


def _default_static_runner(image: Image.Image, settings: RefineSettings) -> Image.Image:
    from studio.static_mode.refine import StaticRefineEngine

    return StaticRefineEngine(settings).refine(image, asset_type="PIXEL_SCENE", cleanup=False).logical


def run_case(
    case: BenchmarkCase,
    *,
    sprite_settings: RefineSettings | None = None,
    static_settings: RefineSettings | None = None,
    sprite_runner: SpriteRunner = _default_sprite_runner,
    static_runner: StaticRunner = _default_static_runner,
) -> CaseResult:
    """Degrade one case, run it through refine, and score it against the truth."""
    degraded = [
        degrade(upscale(frame, case.upscale), list(case.degradations), strength=case.strength)
        for frame in case.frames
    ]
    warnings: list[str] = []
    if case.mode == "sprite":
        settings = sprite_settings or load_refine_settings("sprite")
        recovered = list(sprite_runner(degraded, settings))
        metrics = sprite_metrics(case.frames[0], recovered[0])
        metrics["temporal"] = temporal_consistency(recovered)
        if recovered[0].size != case.frames[0].size:
            warnings.append(f"recovered logical size {recovered[0].size} != ground truth {case.frames[0].size}")
    else:
        settings = static_settings or load_refine_settings("static")
        recovered_image = static_runner(degraded[0], settings)
        metrics = static_metrics(case.frames[0], recovered_image)
        if recovered_image.size != case.frames[0].size:
            warnings.append(f"recovered logical size {recovered_image.size} != ground truth {case.frames[0].size}")
    return CaseResult(
        name=case.name, mode=case.mode, degradations=case.degradations,
        metrics=metrics, warnings=tuple(warnings),
    )


def run_benchmark(cases: Sequence[BenchmarkCase] | None = None, **kwargs: Any) -> BenchmarkReport:
    report = BenchmarkReport()
    for case in cases or default_cases():
        report.results.append(run_case(case, **kwargs))
    return report


def compare_runs(baseline: dict[str, Any], candidate: dict[str, Any], *, tolerance: float = 1e-6) -> dict[str, Any]:
    """Diff two benchmark reports so a regression cannot hide behind an average.

    Reports per-case movement on the headline metric for each mode. A change
    that lifts the mean while dropping three cases is a regression with good
    marketing, and this is what makes that visible.
    """
    def index(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
        return {case["case"]: case for case in report.get("cases", [])}

    before, after = index(baseline), index(candidate)
    moved: list[dict[str, Any]] = []
    for name in sorted(set(before) | set(after)):
        if name not in before:
            moved.append({"case": name, "change": "added"})
            continue
        if name not in after:
            moved.append({"case": name, "change": "removed"})
            continue
        keys = ("silhouette", "iou") if before[name]["mode"] == "sprite" else ("color", "mean_delta_e")
        old = (before[name]["metrics"].get(keys[0]) or {}).get(keys[1])
        new = (after[name]["metrics"].get(keys[0]) or {}).get(keys[1])
        if old is None or new is None or abs(float(new) - float(old)) <= tolerance:
            continue
        # Higher IoU is better; lower colour error is better.
        improved = float(new) > float(old) if keys[0] == "silhouette" else float(new) < float(old)
        moved.append(
            {
                "case": name,
                "metric": f"{keys[0]}.{keys[1]}",
                "before": old,
                "after": new,
                "change": "improved" if improved else "regressed",
            }
        )
    return {
        "kind": "asset-studio-benchmark-comparison",
        "moved": moved,
        "regressions": [item for item in moved if item.get("change") == "regressed"],
        "improvements": [item for item in moved if item.get("change") == "improved"],
    }
