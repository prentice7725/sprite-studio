# Pixelize Phase 1 Benchmark Summary

- Generated: `2026-09-17T23:39:19+0900`
- Repository revision: `1abe98d`
- Config: `benchmark/configs/benchmark_matrix.json`
- Dataset: `synthetic-proxy-v1` with `10` deterministic synthetic proxy sources (D01–D10)
- Scope: A1 current M1.1, A2 geometry-first + BOX, A3 geometry-first + LANCZOS

## Executive result

At the focus configuration (`size=128`, `palette=auto`, `detail=balanced`), the objective proxy winner is **A1 Current M1.1** with a mean heuristic score of **97.937/100** across 10 sources.

This is an engineering screening result, not a replacement for the Phase 1 human rubric. The heuristic combines silhouette IoU, thin-feature recovery, fragmentation, binary alpha, and palette compliance; it does not claim face readability or style faithfulness.

## Focus comparison

| Method | Cases | Heuristic /100 | Runtime ms | Silhouette IoU | Thin recovery | Tiny-color ratio | Determinism | Palette violations |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| A1 Current M1.1 | 10 | 97.937 | 1387.092 | 0.958 | 1.0 | 0.001 | 1.0 | 0 |
| A2 Geometry-first + BOX | 10 | 87.562 | 57.966 | 0.993 | 0.959 | 0.037 | 1.0 | 0 |
| A3 Geometry-first + LANCZOS | 10 | 82.908 | 73.226 | 0.996 | 0.923 | 0.123 | 1.0 | 0 |

## Per-source focus winners

| Source | Winner by heuristic | Score | A1 | A2 | A3 |
|---|---|---:|---:|---:|---:|
| D01 front-readable | A1 Current M1.1 | 98.03 | 98.03 | 91.352 | 83.442 |
| D02 three-quarter | A1 Current M1.1 | 97.92 | 97.92 | 88.239 | 83.257 |
| D03 mascot | A1 Current M1.1 | 98.822 | 98.822 | 89.362 | 82.437 |
| D04 detailed-costume | A1 Current M1.1 | 98.157 | 98.157 | 85.846 | 82.536 |
| D05 long-hair | A1 Current M1.1 | 98.4 | 98.4 | 83.841 | 82.739 |
| D06 weapon | A1 Current M1.1 | 97.612 | 97.612 | 88.528 | 82.679 |
| D07 transparent-accessory | A1 Current M1.1 | 97.247 | 97.247 | 86.199 | 83.039 |
| D08 opaque-background | A1 Current M1.1 | 97.586 | 97.586 | 88.304 | 83.051 |
| D09 multiple-subjects | A1 Current M1.1 | 97.932 | 97.932 | 89.991 | 82.94 |
| D10 low-contrast | A1 Current M1.1 | 97.661 | 97.661 | 83.955 | 82.963 |

## Findings and decision

- The full matrix contains `330` completed case records (three sizes, Auto/32/48 palettes, Balanced detail, plus Clean and Detailed at 128/Auto).
- Every case records an exact PNG SHA-256 repeat check. A failed determinism check is a hard follow-up item before promoting a candidate.
- The synthetic set intentionally covers transparent sources, opaque-background cleanup, multiple subjects, narrow accessories, long hair, weapons, and low-contrast interiors. It is useful for operation-order screening but cannot validate production style faithfulness.
- Human review status: **pending** (`0` scored rows). Fill `benchmark/reports/human_scores.csv` using the 1–5 rubric before making a final visual-quality promotion decision.

### Recommended next move

Keep A1 as the production baseline while using **A1 Current M1.1** as the Phase 2 comparison candidate. Next add one stronger palette-after-geometry candidate (DPID/PIA-like or a controlled perceptual variant), then rerun this same matrix and the human sheet. Do not delete or silently replace the existing M1.1 route based on the proxy score alone.

## Artifacts

- [`benchmark_results.json`](benchmark_results.json) — machine-readable full result set and aggregates
- [`benchmark_scores.csv`](benchmark_scores.csv) — flat metric table
- [`human_scores.csv`](human_scores.csv) — fillable human-review sheet
- [`human_scores_template.csv`](human_scores_template.csv) — blank rubric template
- [`../sheets/by_source`](../sheets/by_source) — per-source A1/A2/A3 focus sheets
- [`../sheets/by_method`](../sheets/by_method) — per-method source overview sheets

## Reproduction

```powershell
python tools/pixelize_benchmark.py --bootstrap-synthetic --force
python tools/pixelize_benchmark.py  # restartable; matching cases are skipped
```

Phase 1 deliberately excludes external image generation, human-score fabrication, and app/UI redesign. Those belong to later phases or manual review.
